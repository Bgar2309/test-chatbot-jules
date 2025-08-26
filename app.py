import os
import sys
from flask import Flask, request, jsonify, render_template
from supabase import create_client, Client
from openai import OpenAI
from mistralai.client import MistralClient
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Environment Variable Check ---
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
openai_api_key = os.environ.get("OPENAI_API_KEY")
mistral_api_key = os.environ.get("MISTRAL_API_KEY")

if not all([supabase_url, supabase_key, openai_api_key, mistral_api_key]):
    print("---" * 10)
    print("ERROR: Missing required environment variables.")
    print("Please ensure your .env file is correctly set up with:")
    print("- SUPABASE_URL")
    print("- SUPABASE_KEY")
    print("- OPENAI_API_KEY")
    print("- MISTRAL_API_KEY")
    print("---" * 10)
    sys.exit(1)

# --- Client Initialization ---
try:
    supabase: Client = create_client(supabase_url, supabase_key)
    openai_client = OpenAI(api_key=openai_api_key)
    mistral_client = MistralClient(api_key=mistral_api_key)
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
    warehouse TEXT NOT NULL DEFAULT 'NJ',
    created_at TIMESTAMPTZ DEFAULT now()
);
"""

WAREHOUSE_INFO = {
    'NJ': 'New Jersey',
    'CA': 'California', 
    'TX': 'Texas',
    'ALL': 'All Warehouses'
}

# --- Core Logic Functions ---
def parse_warehouse_filter(user_question):
    """
    Analyse la question de l'utilisateur pour déterminer quel(s) entrepôt(s) interroger.
    
    Returns:
        list: Liste des codes d'entrepôts à interroger ['NJ', 'CA', 'TX'] ou ['ALL']
    """
    question_lower = user_question.lower()
    
    warehouses = []
    
    # Recherche de mots-clés spécifiques
    if any(keyword in question_lower for keyword in ['new jersey', 'nj warehouse', 'jersey']):
        warehouses.append('NJ')
    
    if any(keyword in question_lower for keyword in ['california', 'ca warehouse', 'calif']):
        warehouses.append('CA')
        
    if any(keyword in question_lower for keyword in ['texas', 'tx warehouse']):
        warehouses.append('TX')
    
    # Si aucun entrepôt spécifique mentionné, chercher dans tous
    if not warehouses:
        if any(keyword in question_lower for keyword in ['all warehouses', 'everywhere', 'total', 'all locations']):
            return ['ALL']
        else:
            # Par défaut, chercher dans NJ (le plus gros entrepôt)
            return ['NJ']
    
    return warehouses

def get_sql_from_llm(user_question, history, model, warehouses):
    """
    Uses the selected LLM to convert a user's question into a SQL query.
    Modifié pour supporter le filtrage par entrepôt.
    """
    
    # Construire la clause WHERE pour les entrepôts
    if 'ALL' in warehouses:
        warehouse_clause = ""  # Pas de filtre sur warehouse
        warehouse_info = "Searching in ALL warehouses (NJ, CA, TX)"
    else:
        if len(warehouses) == 1:
            warehouse_clause = f"WHERE warehouse = '{warehouses[0]}'"
            warehouse_info = f"Searching in {WAREHOUSE_INFO.get(warehouses[0], warehouses[0])} warehouse only"
        else:
            warehouse_list = "', '".join(warehouses)
            warehouse_clause = f"WHERE warehouse IN ('{warehouse_list}')"
            warehouse_names = [WAREHOUSE_INFO.get(w, w) for w in warehouses]
            warehouse_info = f"Searching in {', '.join(warehouse_names)} warehouses"
    
    system_prompt = f"""
    You are a hyper-specialized SQL generation bot. Your single purpose is to convert user questions into a valid PostgreSQL query for the `inventory` table. You must adhere to the following rules with no exceptions.

    **WAREHOUSE FILTERING:**
    {warehouse_info}
    
    **Primary Directive: Date Queries**
    - The user's concept of "date", "latest", "newest", or "most recent" ALWAYS refers to the `date_of_inventory` column.
    - The `created_at` column is a technical field and you are FORBIDDEN from using it in any `ORDER BY` clause for date-related queries.
    - When the user asks for the "latest" or "most recent" item, your query MUST:
        1. Apply warehouse filter: {warehouse_clause if warehouse_clause else "No warehouse filter needed"}
        2. Filter for entries where the inventory date exists: `AND date_of_inventory IS NOT NULL AND date_of_inventory != ''`
        3. Order the results by inventory date: `ORDER BY date_of_inventory DESC`
        4. Return only the top result: `LIMIT 1`

    **General Query Rules:**
    - Table name: `inventory`
    - Schema (now includes warehouse field):
      {TABLE_SCHEMA}
    - ALWAYS include the warehouse filter when specified: {warehouse_clause}
    - For string comparisons (e.g., on `stencil` or `silkscreen`), always use `TRIM()` and `ILIKE` for case-insensitive and whitespace-tolerant matching.
    - Unless the user asks for a specific count, always select all columns: `SELECT *`.
    - Include warehouse information in results by always selecting the warehouse column.
    - Limit all queries to a maximum of 20 rows (`LIMIT 20`) unless a different limit is requested.
    
    **Example queries:**
    - For latest item in NJ: `SELECT * FROM inventory WHERE warehouse = 'NJ' AND date_of_inventory IS NOT NULL AND date_of_inventory != '' ORDER BY date_of_inventory DESC LIMIT 1;`
    - For count by warehouse: `SELECT warehouse, COUNT(*) FROM inventory {warehouse_clause} GROUP BY warehouse;`
    - For searching stencil across warehouses: `SELECT * FROM inventory {warehouse_clause + ' AND' if warehouse_clause else 'WHERE'} TRIM(stencil) ILIKE '%search_term%' LIMIT 20;`

    **Output Format:**
    - You must only respond with the raw SQL query. No explanations, no markdown, no "```sql".
    """

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_question})

    try:
        if "mistral" in model.lower():
            response = mistral_client.chat(
                model=model,
                messages=messages,
                temperature=0,
            )
        else:
            response = openai_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
            )

        sql_query = response.choices[0].message.content.strip()
        if not sql_query.upper().startswith("SELECT"):
            return None
        return sql_query
    except Exception as e:
        print(f"Error generating SQL query with model {model}: {e}")
        return None

def get_response_from_llm(user_question, db_results, history, model, warehouses):
    """
    Uses the selected LLM to generate a natural language response.
    Modifié pour inclure l'information sur les entrepôts recherchés.
    """
    
    # Information sur les entrepôts recherchés
    if 'ALL' in warehouses:
        warehouse_context = "Searched in ALL warehouses (New Jersey, California, Texas)"
    else:
        warehouse_names = [WAREHOUSE_INFO.get(w, w) for w in warehouses]
        warehouse_context = f"Searched in: {', '.join(warehouse_names)}"
    
    system_prompt = f"""
    You are a helpful but strictly factual chatbot assistant for a multi-warehouse stencil inventory system. 
    
    **Search Context:** {warehouse_context}
    
    Your task is to present information from database search results. You must be precise and never invent information.

    **Primary Directive: Factual Reporting**
    - You MUST only use information explicitly provided in the "Database search results".
    - If a field in the database result is empty, null, or not present, you MUST state "Not specified" or "Not available".
    - **DO NOT HALLUCINATE:** Under no circumstances should you invent, guess, or infer a value for a field that is empty.

    **Formatting Instructions:**
    - ALWAYS mention which warehouse(s) were searched at the beginning of your response.
    - Present each piece of information on a new line with a clear label.
    - **NEVER display the `id` or `created_at` columns.** These are internal database fields.
    - **ALWAYS display the `warehouse` field** as "Warehouse: [Name]" (convert NJ→New Jersey, CA→California, TX→Texas).
    - Translate `orientation`: 'HRZ' to 'Horizontal', 'VERT' to 'Vertical'.
    - The primary date to show the user is from the `date_of_inventory` column. Label it "Date of Inventory:".
    
    **Multi-warehouse considerations:**
    - When results come from multiple warehouses, group them by warehouse or clearly indicate the warehouse for each item.
    - For count queries, clearly break down results by warehouse.

    **Response Logic:**
    - If the database results are empty, inform the user that you couldn't find any information matching their request in the specified warehouse(s).
    - If the database query resulted in an error, apologize and say there was a problem retrieving the data.
    - Use the conversation history to understand the context of the user's question.
    """

    if db_results and 'error' in db_results:
        results_str = f"An error occurred: {db_results['error']}"
    elif not db_results:
        results_str = "No results found."
    else:
        results_str = "\n".join([str(row) for row in db_results])

    history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
    prompt = f"""
    Search context: {warehouse_context}
    
    Here is the conversation history:
    {history_str}

    User's latest question: "{user_question}"
    Database search results:
    {results_str}

    Based on this, provide a helpful response that clearly indicates which warehouse(s) were searched.
    Your response:
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    try:
        if "mistral" in model.lower():
            response = mistral_client.chat(
                model=model,
                messages=messages,
                temperature=0.7,
            )
        else:
            response = openai_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
            )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error generating final response with model {model}: {e}")
        return "Sorry, I encountered an error while formulating a response."

# --- Flask Routes ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    """
    The main chat endpoint, now with warehouse filtering.
    """
    data = request.get_json()
    user_question = data.get("message")
    history = data.get("history", [])
    model = data.get("model", "gpt-4o-mini")  # Default to OpenAI model
    
    if not user_question:
        return jsonify({"error": "No message provided"}), 400
    
    # Déterminer quel(s) entrepôt(s) interroger
    warehouses = parse_warehouse_filter(user_question)
    print(f"🏭 Warehouses to search: {warehouses}")
    
    sql_query = get_sql_from_llm(user_question, history, model, warehouses)
    if not sql_query:
        return jsonify({"response": "Sorry, I couldn't understand your request. Could you please rephrase it?"})

    cleaned_sql_query = sql_query.strip().rstrip(';')
    print(f"Generated SQL Query with {model}: {cleaned_sql_query}")

    try:
        rpc_params = {'query': cleaned_sql_query}
        db_results = supabase.rpc('execute_sql', rpc_params).execute().data
    except Exception as e:
        print(f"Error executing Supabase RPC: {e}")
        db_results = {'error': str(e)}

    print(f"Database results: {db_results}")

    final_response = get_response_from_llm(user_question, db_results, history, model, warehouses)
    return jsonify({"response": final_response})

@app.route('/warehouses', methods=['GET'])
def get_warehouses():
    """
    Endpoint pour récupérer les statistiques des entrepôts.
    """
    try:
        stats = supabase.table("inventory_stats").select("*").execute().data
        return jsonify({"warehouses": stats})
    except Exception as e:
        print(f"Error fetching warehouse stats: {e}")
        return jsonify({"error": str(e)}), 500

# --- Main Execution ---
if __name__ == '__main__':
    print("Application is ready to start.")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)