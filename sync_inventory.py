import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# --- Environment and Client Initialization ---
load_dotenv()

# --- Constants ---
# Directories
NEW_FILES_DIR = "nouveaux_fichiers/"
ARCHIVE_DIR = "archives/"
REVIEW_DIR = "for_review/"

# Define the final list of columns that should be in the dataframe.
# This ensures consistency and matches the database schema expectations.
FINAL_COLUMNS = [
    "STENCIL",
    "ORIENTATION",
    "INVOICE #",
    "CONE SIZE",
    "# OF LINES",
    "MISC. INFO",
    "DATE",
    "SILKSCREEN"
]

# --- Core Functions ---

def clean_dataframe(df):
    """
    Cleans a single DataFrame by removing empty rows, standardizing
    column names, and renaming alternate column names.
    """
    # Drop rows where all elements are NaN (empty rows)
    df.dropna(how='all', inplace=True)
    if df.empty:
        return df

    # Standardize column names (uppercase and stripped whitespace)
    df.columns = [str(col).strip().upper() for col in df.columns]

    # Rename 'STENCILS' to 'STENCIL' if it exists for consistency
    if 'STENCILS' in df.columns:
        df.rename(columns={'STENCILS': 'STENCIL'}, inplace=True)

    return df


def find_new_file():
    """
    Finds the oldest Excel file in the NEW_FILES_DIR.
    Returns the full path to the file, or None if no file is found.
    """
    try:
        files = [os.path.join(NEW_FILES_DIR, f) for f in os.listdir(NEW_FILES_DIR) if f.endswith(('.xlsx', '.xls'))]
        if not files:
            return None
        # Return the oldest file based on modification time
        return min(files, key=os.path.getmtime)
    except FileNotFoundError:
        print(f"Error: The directory '{NEW_FILES_DIR}' was not found.")
        return None


def load_and_clean_excel_file(excel_path):
    """
    Reads all relevant sheets from an Excel file, cleans the data from each sheet,
    concatenates them, and returns a single, clean DataFrame.
    """
    all_cleaned_dfs = []
    with pd.ExcelFile(excel_path) as xls:
        sheet_names = xls.sheet_names

        if len(sheet_names) <= 1:
            print("Warning: Only one sheet found. No other sheets to process.")
            return pd.DataFrame(columns=FINAL_COLUMNS)

        # Skip the first sheet, as per the original script's logic
        sheets_to_process = sheet_names[1:]
        print(f"Processing sheets: {sheets_to_process}")

        for sheet in sheets_to_process:
            df = pd.read_excel(xls, sheet_name=sheet)
            if df.empty:
                continue

            cleaned_df = clean_dataframe(df)
            if not cleaned_df.empty:
                all_cleaned_dfs.append(cleaned_df)

    if not all_cleaned_dfs:
        print("No data found in the sheets to process.")
        return pd.DataFrame(columns=FINAL_COLUMNS)

    # Concatenate all cleaned DataFrames into one
    combined_df = pd.concat(all_cleaned_dfs, ignore_index=True)

    # Ensure the final DataFrame has all required columns in the correct order
    final_df = pd.DataFrame()
    for col in FINAL_COLUMNS:
        if col in combined_df.columns:
            final_df[col] = combined_df[col]
        else:
            # Add missing columns with None, so it's consistent
            final_df[col] = None

    return final_df

def create_unique_ids(df):
    """
    Creates a unique ID for each row by combining the item identifier and the date.
    It handles the STENCIL/SILKSCREEN logic and drops rows that cannot be
    uniquely identified.
    """
    if df.empty:
        return df

    # 1. Coalesce STENCIL and SILKSCREEN into a single identifier column
    df['item_identifier'] = df['STENCIL'].fillna(df['SILKSCREEN'])

    # 2. Normalize the identifier to a consistent string format to prevent mismatches
    #    -astype(str): Handles numbers, etc.
    #    -str.strip(): Removes leading/trailing whitespace.
    #    -str.replace(...): Removes trailing '.0' for numeric IDs read as float.
    df['item_identifier'] = df['item_identifier'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)

    # 3. Convert date column, coercing errors to NaT (Not a Time)
    # This handles malformed date strings gracefully.
    df['DATE'] = pd.to_datetime(df['DATE'], errors='coerce')

    # 3. Drop rows that don't have an item_identifier or a valid date (now NaT)
    original_rows = len(df)
    df.dropna(subset=['item_identifier', 'DATE'], inplace=True)
    if len(df) < original_rows:
        print(f"Dropped {original_rows - len(df)} rows with missing identifier or invalid date.")

    # 4. Create the unique ID now that data is clean
    df['date_str'] = df['DATE'].dt.strftime('%Y-%m-%d')
    df['unique_id'] = df['item_identifier'].astype(str) + '_' + df['date_str']

    # 5. Clean up temporary columns
    df.drop(columns=['item_identifier', 'date_str'], inplace=True)

    return df


def main():
    """
    Main function to run the synchronization process.
    """
    print("--- Starting Inventory Sync Process ---")

    # 1. Find a new file to process
    new_file_path = find_new_file()
    if not new_file_path:
        print("No new files to process in the 'nouveaux_fichiers/' directory.")
        print("--- Sync Process Finished ---")
        return

    print(f"Found new file: {new_file_path}")

    # 2. Load and clean the data from the Excel file
    try:
        data_from_excel = load_and_clean_excel_file(new_file_path)
        if data_from_excel.empty:
            print("The Excel file was empty or contained no processable data.")
            # We should probably archive the empty file here as well.
            return
        else:
            print(f"Successfully loaded and cleaned {len(data_from_excel)} rows from the file.")

        # 3. Create unique IDs for the data
        data_with_ids = create_unique_ids(data_from_excel)
        print(f"Generated unique IDs for {len(data_with_ids)} valid rows.")

        # For now, just display the first 5 rows with the new ID
        print("Data preview with unique_id:")
        print(data_with_ids.head())

    except Exception as e:
        print(f"An error occurred while processing the file {new_file_path}: {e}")
        # Decide if the file should be moved to an error folder or left alone
        return

def get_existing_data_from_supabase():
    """
    Fetches the inventory data from Supabase and returns a DataFrame
    with unique_ids.
    """
    print("Fetching existing data from Supabase...")
    try:
        # Initialize Supabase client
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            print("Error: Supabase credentials not found in .env file.")
            return None
        supabase: Client = create_client(supabase_url, supabase_key)

        # Select only the columns needed to build the unique ID
        response = supabase.table('inventory').select('stencil', 'silkscreen', 'date_of_inventory').execute()

        if response.data:
            # Convert the data to a pandas DataFrame
            db_df = pd.DataFrame(response.data)

            # Rename columns to match the Excel file column names for consistent processing
            db_df.rename(columns={
                'stencil': 'STENCIL',
                'silkscreen': 'SILKSCREEN',
                'date_of_inventory': 'DATE'
            }, inplace=True)

            # Generate unique IDs using the same function as for the Excel data
            db_df_with_ids = create_unique_ids(db_df)

            # Return a set of unique IDs for efficient lookup
            return set(db_df_with_ids['unique_id'])
        else:
            print("No data found in Supabase table 'inventory'.")
            return set()

    except Exception as e:
        print(f"An error occurred while fetching data from Supabase: {e}")
        return None


def main():
    """
    Main function to run the synchronization process.
    """
    print("--- Starting Inventory Sync Process ---")

    # 1. Fetch existing data from Supabase first
    existing_ids = get_existing_data_from_supabase()
    if existing_ids is None:
        print("Could not proceed due to an error fetching from Supabase.")
        return

    print(f"Found {len(existing_ids)} existing unique entries in the database.")

    # 2. Find a new file to process
    new_file_path = find_new_file()
    if not new_file_path:
        print("No new files to process in the 'nouveaux_fichiers/' directory.")
        print("--- Sync Process Finished ---")
        return

    print(f"Found new file: {new_file_path}")

    # 3. Load and clean the data from the Excel file
    try:
        data_from_excel = load_and_clean_excel_file(new_file_path)
        if data_from_excel.empty:
            print("The Excel file was empty or contained no processable data.")
            return
        else:
            print(f"Successfully loaded and cleaned {len(data_from_excel)} rows from the file.")

        # 4. Create unique IDs for the data
        data_with_ids = create_unique_ids(data_from_excel)
        print(f"Generated unique IDs for {len(data_with_ids)} valid rows.")

        # For now, just display the first 5 rows with the new ID
        print("Data preview with unique_id:")
        print(data_with_ids.head())

    except Exception as e:
        print(f"An error occurred while processing the file {new_file_path}: {e}")
        return

def filter_new_entries(df, existing_ids_set):
    """
    Filters the DataFrame to return only the rows with unique_ids that
    are not in the existing_ids_set.
    """
    if df.empty:
        return df

    initial_rows = len(df)
    new_entries_df = df[~df['unique_id'].isin(existing_ids_set)].copy()
    print(f"Comparison complete. Found {len(new_entries_df)} new entries out of {initial_rows} total valid rows.")

    return new_entries_df


def main():
    """
    Main function to run the synchronization process.
    """
    print("--- Starting Inventory Sync Process ---")

    # 1. Fetch existing data from Supabase first
    existing_ids = get_existing_data_from_supabase()
    if existing_ids is None:
        print("Could not proceed due to an error fetching from Supabase.")
        return

    print(f"Found {len(existing_ids)} existing unique entries in the database.")

    # 2. Find a new file to process
    new_file_path = find_new_file()
    if not new_file_path:
        print("No new files to process in the 'nouveaux_fichiers/' directory.")
        print("--- Sync Process Finished ---")
        return

    print(f"Found new file: {new_file_path}")

    # 3. Load, clean, and generate IDs from the Excel file
    try:
        data_from_excel = load_and_clean_excel_file(new_file_path)
        if data_from_excel.empty:
            print("The Excel file was empty or contained no processable data.")
            return

        data_with_ids = create_unique_ids(data_from_excel)
        print(f"Generated unique IDs for {len(data_with_ids)} valid rows from the Excel file.")

        # 4. Compare the Excel data with the database data
        new_entries = filter_new_entries(data_with_ids, existing_ids)

        if not new_entries.empty:
            print("Preview of new entries found:")
            print(new_entries.head())
        else:
            print("No new entries found. The database is already up-to-date.")

    except Exception as e:
        print(f"An error occurred while processing the file {new_file_path}: {e}")
        return

    # The next steps (manual validation, insertion) will be added here.

def insert_data_to_supabase(df):
    """
    Prepares the dataframe and inserts the new entries into the Supabase 'inventory' table.
    """
    if df.empty:
        print("No data to insert.")
        return

    # 1. Drop the temporary 'unique_id' column before insertion
    df_to_insert = df.drop(columns=['unique_id'])

    # 2. Rename columns to match the database schema
    df_to_insert.rename(columns={
        "STENCIL": "stencil",
        "ORIENTATION": "orientation",
        "INVOICE #": "invoice_number",
        "CONE SIZE": "cone_size",
        "# OF LINES": "number_of_lines",
        "MISC. INFO": "misc_info",
        "DATE": "date_of_inventory",
        "SILKSCREEN": "silkscreen"
    }, inplace=True)

    # 3. Convert DataFrame to a list of dictionaries for Supabase.
    #    - Supabase client prefers JSON-serializable types, so we handle NaNs by converting them to None.
    df_to_insert = df_to_insert.where(pd.notna(df_to_insert), None)
    records = df_to_insert.to_dict(orient="records")

    # 4. Insert the data into the 'inventory' table
    try:
        # Initialize Supabase client
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            print("Error: Supabase credentials not found in .env file.")
            return
        supabase: Client = create_client(supabase_url, supabase_key)

        print(f"Inserting {len(records)} new records into Supabase...")
        response = supabase.table("inventory").insert(records).execute()

        # Supabase API v2 returns a model with a 'data' attribute
        if response.data:
            print(f"Successfully inserted {len(response.data)} records.")
        else:
            # Handle potential errors if the response structure is different
            print("Insertion completed, but no data was returned in the response.")

    except Exception as e:
        print(f"An error occurred during data insertion: {e}")


def request_user_validation(new_entries_df):
    """
    Displays the new entries to the user, saves them to a review file,
    and asks for confirmation before proceeding.
    """
    if new_entries_df.empty:
        print("No new entries to insert.")
        return False

    # Create the review directory if it doesn't exist
    os.makedirs(REVIEW_DIR, exist_ok=True)

    # Save the new entries to a CSV for review
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_filepath = os.path.join(REVIEW_DIR, f"new_entries_for_review_{timestamp}.csv")
    new_entries_df.to_csv(review_filepath, index=False)

    print("\n--- User Validation Required ---")
    print(f"Found {len(new_entries_df)} new entries to be added.")
    print(f"A CSV file with these entries has been saved to: {review_filepath}")
    print("\nPreview of new entries:")
    print(new_entries_df.to_string()) # Use to_string() to print all rows without truncation

    try:
        user_response = input("\nDo you want to insert these entries into the database? (yes/no): ").lower().strip()
        if user_response == 'yes':
            print("User approved. Proceeding with insertion...")
            return True
        else:
            print("User rejected. Aborting insertion.")
            return False
    except KeyboardInterrupt:
        print("\nInsertion cancelled by user.")
        return False


def main():
    """
    Main function to run the synchronization process.
    """
    print("--- Starting Inventory Sync Process ---")

    # 1. Fetch existing data from Supabase first
    existing_ids = get_existing_data_from_supabase()
    if existing_ids is None:
        return
    print(f"Found {len(existing_ids)} existing unique entries in the database.")

    # 2. Find and process a new file
    new_file_path = find_new_file()
    if not new_file_path:
        print("No new files to process.")
        return
    print(f"Found new file: {new_file_path}")

    try:
        data_with_ids = create_unique_ids(load_and_clean_excel_file(new_file_path))
        print(f"Generated unique IDs for {len(data_with_ids)} valid rows from the Excel file.")

        # 3. Compare and get new entries
        new_entries = filter_new_entries(data_with_ids, existing_ids)

        # 4. Request user validation
        if request_user_validation(new_entries):
            insert_data_to_supabase(new_entries)

    except Exception as e:
        print(f"An error occurred while processing the file {new_file_path}: {e}")
        return

    # Archive the processed file
    archive_processed_file(new_file_path)

    print("--- Sync Process Finished ---")

def archive_processed_file(file_path):
    """
    Moves the processed file to the archive directory with a timestamp.
    """
    if not os.path.exists(file_path):
        return

    filename = os.path.basename(file_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = os.path.join(ARCHIVE_DIR, f"{timestamp}_{filename}")

    try:
        os.rename(file_path, archive_path)
        print(f"Successfully archived processed file to: {archive_path}")
    except OSError as e:
        print(f"Error archiving file {file_path}: {e}")


if __name__ == "__main__":
    # Ensure the necessary directories exist
    os.makedirs(NEW_FILES_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(REVIEW_DIR, exist_ok=True)
    main()
