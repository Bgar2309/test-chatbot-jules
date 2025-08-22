import os
import pandas as pd
from supabase import create_client, Client
from dotenv import load_dotenv

def setup_supabase():
    """
    Connects to Supabase, cleans the CSV data, and uploads it to the 'inventory' table.
    """
    load_dotenv()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_KEY must be set in a .env file.")
        print("Please create a .env file and add your Supabase credentials.")
        print("You can use .env.example as a template.")
        return

    try:
        supabase: Client = create_client(supabase_url, supabase_key)

        # 1. Read the CSV file
        df = pd.read_csv("inventory.csv")

        # 2. Clean column names
        df.rename(columns={
            "STENCIL": "stencil",
            "ORIENTATION": "orientation",
            "INVOICE #": "invoice_number",
            "CONE SIZE": "cone_size",
            "# OF LINES": "number_of_lines",
            "MISC. INFO": "misc_info",
            "DATE": "date_of_inventory",
            "SILKSCREEN": "silkscreen"
        }, inplace=True)

        # 3. Convert DataFrame to a list of dictionaries for Supabase
        #    - Supabase client prefers JSON-serializable types, so we handle NaNs.
        df = df.where(pd.notna(df), None)
        records = df.to_dict(orient="records")

        # 4. Insert the data into the 'inventory' table
        #    The user must have already created the table using schema.sql
        print("Uploading data to Supabase... This may take a moment.")
        data, count = supabase.table("inventory").insert(records).execute()

        # The response format from Supabase's execute() is a tuple (data, count)
        # We check the 'data' part of the response to see if there was an error.
        if data[0] == 'error':
             print(f"Error uploading data: {data[1]}")
        else:
             print(f"Successfully uploaded {len(records)} records to the 'inventory' table.")


    except Exception as e:
        print(f"An error occurred: {e}")
        print("\nPlease ensure you have:")
        print("1. Created a .env file with your Supabase credentials (use .env.example as a template).")
        print("2. Run the SQL code in 'schema.sql' in your Supabase project's SQL Editor to create the 'inventory' table.")

if __name__ == "__main__":
    setup_supabase()
