import os
import sys
from flask import Flask, request, jsonify, render_template
from supabase import create_client, Client
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Environment Variable Check ---
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
openai_api_key = os.environ.get("OPENAI_API_KEY")

if not all([supabase_url, supabase_key, openai_api_key]):
    print("---" * 10)
    print("ERROR: Missing required environment variables.")
    print("Please ensure your .env file is correctly set up with:")
    print("- SUPABASE_URL")
    print("- SUPABASE_KEY")
    print("- OPENAI_API_KEY")
    print("---" * 10)
    sys.exit(1)

# --- Client Initialization ---
try:
    supabase: Client = create_client(supabase_url, supabase_key)
    client = OpenAI(api_key=openai_api_key)
except Exception as e:
    print(f"Error initializing clients: {e}")
    sys.exit(1)

# --- Flask App Initialization ---
app = Flask(__name__)

# --- App Constants ---
TABLE_SCHEMA = """
CREATE TABLE inventory (
    id BIGINT PRIMARY KEY,
    stencil TEXT,
    orientation TEXT,
    invoice_number TEXT,
    cone_size TEXT,
    number_of_lines TEXT,
    misc_info TEXT,
    date_of_inventory TEXT
);
"""

# --- Core Logic Functions ---
def get_sql_from_llm(user_question, history):
    """
    Uses OpenAI to convert a user's question into a SQL query, using conversation history for context.
    """
    system_prompt = f"""
    You are an expert SQL assistant. Your task is to generate a SQL query based on a user's question and the conversation history.
    You must only respond with the SQL query, and nothing else.
    The query will be executed against a PostgreSQL database with the following table schema:
    {TABLE_SCHEMA}
    - The table is named 'inventory'.
    - The `stencil` column contains the name or code of the stencil.
    - The `orientation` column is likely 'HRZ' (horizontal) or 'VERT' (vertical).
    - The `date_of_inventory` column stores dates as text.
    - **Crucially, to handle whitespace issues in the data, always wrap the column name in the `TRIM()` function when performing string comparisons in a `WHERE` clause (e.g., `WHERE TRIM(stencil) ILIKE '%search_term%'`).**
    - **Important: When a user asks about a type of item, such as a 'silkscreen', this information is located in the `MISC. INFO` column. You must search for the term in the `MISC. INFO` column (e.g., `WHERE "MISC. INFO" ILIKE '%silkscreen%'`).**
    - Perform case-insensitive searches using the `ILIKE` operator.
    - If the user asks for a specific item, use the `=` or `ILIKE` operator. If they are asking a more general question, use `ILIKE` with wildcards (`%`).
    - If the user asks a general question, try to return all relevant rows.
    - ALWAYS limit the query to 20 rows using 'LIMIT 20'.
    - Do not include any characters like ```sql or ``` in your response.
    - Use the conversation history to understand context for follow-up questions. For example, if a user asks "how many are there?", look at the previous question to understand what "they" refers to.
    """

    messages = [{"role": "system", "content": system_prompt}]
    # Add history messages
    for message in history:
        messages.append({"role": message["role"], "content": message["content"]})
    # Add the current user question
    messages.append({"role": "user", "content": user_question})


    try:
        response = client.chat.completions.create(
            model="gpt-5-nano",
            messages=messages,
            temperature=0,
        )
        sql_query = response.choices[0].message.content.strip()
        if not sql_query.upper().startswith("SELECT"):
            return None
        return sql_query
    except Exception as e:
        print(f"Error generating SQL query: {e}")
        return None

def get_response_from_llm(user_question, db_results, history):
    """
    Uses OpenAI to generate a natural language response based on the user's question, database results, and conversation history.
    """
    system_prompt = """
    You are a helpful chatbot assistant. Your user has asked a question, and you have retrieved some information from a database.
    Your task is to provide a clear, friendly, and concise answer to the user's question based on the provided database results and the conversation history.
    - Use the conversation history to understand the context of the user's question.
    - If the database results are empty, inform the user that you couldn't find any information matching their request.
    - If there are results, summarize them in a natural way. Do not just list the raw data.
    - If the database query resulted in an error, apologize and say there was a problem retrieving the data.
    """

    if db_results and 'error' in db_results:
        results_str = f"An error occurred: {db_results['error']}"
    elif not db_results:
        results_str = "No results found."
    else:
        results_str = "\n".join([str(row) for row in db_results])

    # Constructing the prompt with history
    history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
    prompt = f"""
    Here is the conversation history:
    {history_str}

    User's latest question: "{user_question}"
    Database search results:
    {results_str}

    Based on this, provide a helpful response.
    Your response:
    """

    try:
        response = client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error generating final response: {e}")
        return "Sorry, I encountered an error while formulating a response."

# --- Flask Routes ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    """
    The main chat endpoint.
    """
    data = request.get_json()
    user_question = data.get("message")
    history = data.get("history", []) # Expect a 'history' key, default to empty list

    if not user_question:
        return jsonify({"error": "No message provided"}), 400

    sql_query = get_sql_from_llm(user_question, history)
    if not sql_query:
        return jsonify({"response": "Sorry, I couldn't understand your request. Could you please rephrase it?"})

    # Clean the generated SQL query
    cleaned_sql_query = sql_query.strip().rstrip(';')
    print(f"Generated SQL Query: {cleaned_sql_query}")

    try:
        rpc_params = {'query': cleaned_sql_query}
        db_results = supabase.rpc('execute_sql', rpc_params).execute().data
    except Exception as e:
        print(f"Error executing Supabase RPC: {e}")
        db_results = {'error': str(e)}

    print(f"Database results: {db_results}")

    final_response = get_response_from_llm(user_question, db_results, history)
    return jsonify({"response": final_response})

# --- Main Execution ---
if __name__ == '__main__':
    print("Application is ready to start.")
    app.run(host='0.0.0.0', port=5000)
