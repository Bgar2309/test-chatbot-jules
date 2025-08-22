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
    date_of_inventory TEXT,
    silkscreen TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
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
    - The `stencil` column contains stencil information.
    - The `silkscreen` column contains silkscreen information.
    - The `orientation` column is either 'HRZ' (horizontal) or 'VERT' (vertical).
    - The `date_of_inventory` column stores dates as text and can be used for sorting. `created_at` is a timestamp that can also be used for finding the most recent entries.
    - **Crucially, to handle whitespace issues in the data, always wrap column names in `TRIM()` when performing string comparisons in a `WHERE` clause (e.g., `WHERE TRIM(stencil) ILIKE '%search_term%'`).**
    - **To get all information for an item, use `SELECT * FROM inventory...`.**
    - **When a user asks for the "latest" or "most recent" entry for something (e.g., "latest silkscreen"), find the relevant item and order by `date_of_inventory` or `created_at` in descending order and limit the result to 1. For example: `SELECT * FROM inventory WHERE silkscreen IS NOT NULL ORDER BY date_of_inventory DESC LIMIT 1;`**
    - Perform case-insensitive searches using the `ILIKE` operator.
    - If the user asks for a specific item, use `ILIKE` with wildcards (`%`).
    - Unless the user asks for a count or a specific number, return all columns (`SELECT *`).
    - ALWAYS limit the query to 20 rows using 'LIMIT 20' unless a specific limit is requested.
    - Do not include any characters like ```sql or ``` in your response.
    - Use the conversation history to understand context for follow-up questions.
    """

    messages = [{"role": "system", "content": system_prompt}]
    # Add history messages
    for message in history:
        messages.append({"role": message["role"], "content": message["content"]})
    # Add the current user question
    messages.append({"role": "user", "content": user_question})


    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
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
    Your task is to provide a clear, friendly, and well-formatted answer based on the provided database results.

    - **Formatting Instructions:**
      - When presenting the details of an inventory item, display each piece of information on a new line for readability.
      - Use clear labels for each field (e.g., "Stencil:", "Orientation:").
      - If a field is empty or null (like `None` or an empty string), either omit it from the response or explicitly state that it's not available (e.g., "Cone Size: Not specified").

    - **Example of a good response:**
      Here is the information for the item you requested:
      - Stencil: ST-1234
      - Orientation: HRZ
      - Invoice Number: 98765
      - Cone Size: Not specified
      - Number of Lines: 2
      - Misc Info: General purpose
      - Date of Inventory: 2023-10-26
      - Silkscreen: SLK-A

    - **Response Logic:**
      - If the database results are empty, inform the user that you couldn't find any information matching their request.
      - If there are multiple results, you can summarize them or present the most relevant one.
      - If the database query resulted in an error, apologize and say there was a problem retrieving the data.
      - Use the conversation history to understand the context of the user's question.
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
            model="gpt-4o-mini",
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
