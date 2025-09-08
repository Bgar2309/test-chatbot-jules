import os
import pandas as pd
from supabase import create_client, Client
from dotenv import load_dotenv
import sys
from datetime import datetime
from pathlib import Path
import glob
import numpy as np
import time

# Configuration des chemins
WAREHOUSE_CONFIG = {
    "NJ": {
        "csv_export": "data/exports/NJ_inventory.csv",
        "name": "New Jersey"
    },
    "CA": {
        "csv_export": "data/exports/CA_inventory.csv",
        "name": "California"
    },
    "TX": {
        "csv_export": "data/exports/TX_inventory.csv", 
        "name": "Texas"
    }
}

def find_excel_file(warehouse_folder, warehouse_code):
    """
    Finds the latest Excel file in the warehouse folder.
    Yields log messages and the final path as ('result', path).
    """
    patterns = [f"{warehouse_code} STENCIL INVENTORY*.xlsx"]
    
    all_files = []
    for pattern in patterns:
        all_files.extend(glob.glob(os.path.join(warehouse_folder, pattern)))
    
    if not all_files:
        # Fallback to any xlsx file if specific patterns don't match
        all_files = glob.glob(os.path.join(warehouse_folder, "*.xlsx"))

    if all_files:
        latest_file = max(all_files, key=os.path.getmtime)
        yield f"📄 Fichier Excel trouvé: {os.path.basename(latest_file)}"
        yield ('result', latest_file)
    else:
        yield ('result', None)

def refresh_inventory_database(warehouse_code=None):
    """
    Erases and recreates data for one or all warehouses.
    This is a generator that yields log messages.
    """
    load_dotenv()
    
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        yield "❌ ERROR: Supabase environment variables are missing."
        yield "__FAILURE__"
        return
    
    try:
        supabase: Client = create_client(supabase_url, supabase_key)
        yield "✅ Connection to Supabase successful."
        
        warehouses_to_process = [warehouse_code.upper()] if warehouse_code else list(WAREHOUSE_CONFIG.keys())
        yield f"🏭 Warehouses to process: {', '.join(warehouses_to_process)}"
        
        success_count = 0
        for warehouse in warehouses_to_process:
            yield f"\n{'='*60}"
            yield f"🏭 Processing warehouse: {WAREHOUSE_CONFIG[warehouse]['name']} ({warehouse})"
            
            warehouse_folder = f"data/warehouses/{warehouse}"
            
            excel_path = None
            for item in find_excel_file(warehouse_folder, warehouse):
                if isinstance(item, tuple) and item[0] == 'result':
                    excel_path = item[1]
                else:
                    yield item

            if not excel_path:
                yield f"⚠️ No Excel file found in: {warehouse_folder}"
                continue
            
            yield f"📊 Reading and cleaning Excel file..."
            df = None
            for item in read_and_clean_excel(excel_path):
                if isinstance(item, tuple) and item[0] == 'result':
                    df = item[1]
                else:
                    yield f"   {item}"

            if df is None or df.empty:
                yield f"❌ No valid data found in {os.path.basename(excel_path)}."
                continue
                
            df['warehouse'] = warehouse
            yield f"📈 Found {len(df)} total entries for {warehouse}."

            # Check existing rows and attempt to delete them
            try:
                count_req = supabase.table("inventory").select("id", count="exact").eq("warehouse", warehouse).execute()
                existing_rows = count_req.count
                yield f"🔍 Found {existing_rows} existing rows for {warehouse} in the database."
                if existing_rows > 0:
                    yield f"🗑️ Deleting {existing_rows} existing rows..."
                    # Note: supabase-py v1 does not easily return the count of deleted rows.
                    # We proceed and verify with a final count later.
                    supabase.table("inventory").delete().eq("warehouse", warehouse).execute()
                    yield "✅ Delete command sent. IMPORTANT: This may fail silently if Row Level Security (RLS) policies are preventing deletion."
            except Exception as e:
                yield f"⚠️ Could not delete data: {e}"
                yield "__FAILURE__"
                continue # Skip to next warehouse

            chunk_size = 100
            total_chunks = (len(df) + chunk_size - 1) // chunk_size
            yield f"📤 Uploading data in {total_chunks} chunks..."
            
            for i in range(0, len(df), chunk_size):
                chunk = df.iloc[i:i + chunk_size]
                chunk_records = chunk.to_dict(orient="records")
                
                for record in chunk_records:
                    for key, value in record.items():
                        if pd.isna(value) or value is None: record[key] = None
                        elif isinstance(value, (pd.Timestamp, datetime, np.datetime64)): record[key] = str(value).split('T')[0]
                        elif isinstance(value, (np.integer, np.floating)): record[key] = value.item()
                        elif isinstance(value, np.bool_): record[key] = bool(value)
                        elif hasattr(value, 'strftime'): record[key] = value.strftime('%Y-%m-%d')
                        elif isinstance(value, str) and value.strip() == '': record[key] = None
                
                try:
                    supabase.table("inventory").insert(chunk_records).execute()
                    yield f"  ✅ Chunk {(i//chunk_size)+1}/{total_chunks} uploaded ({len(chunk_records)} entries)"
                    time.sleep(0.1)
                except Exception as e:
                    yield f"  ❌ Error on chunk {(i//chunk_size)+1}: {e}"
            
            yield "🔍 Final verification..."
            count_result = supabase.table("inventory").select("id", count="exact").eq("warehouse", warehouse).execute()
            if count_result.count == len(df):
                yield f"🎉 Update successful for {warehouse}! ({count_result.count} entries)"
                success_count += 1
            else:
                yield ""
                yield f"🔥🔥🔥 CRITICAL MISMATCH for {warehouse} 🔥🔥🔥"
                yield f"   - Expected Entries: {len(df)}"
                yield f"   - Final Entries in DB: {count_result.count}"
                yield "   - This means the old data was NOT deleted correctly."
                yield "   - LIKELY CAUSE: A Row Level Security (RLS) policy on the 'inventory' table is blocking DELETE operations."
                yield "   - TO FIX: Please go to the Supabase dashboard, navigate to 'Authentication' -> 'Policies', and ensure you have a policy that allows deletes."
                yield ""
        
        yield f"\n{'='*60}"
        yield f"🎯 FINAL SUMMARY"
        yield f"✅ Successfully updated {success_count}/{len(warehouses_to_process)} warehouses."
        
        if success_count == len(warehouses_to_process):
            yield "__SUCCESS__"
        else:
            yield "__FAILURE__"
        
    except Exception as e:
        yield f"❌ An unexpected error occurred: {e}"
        yield "__FAILURE__"

def read_and_clean_excel(excel_path):
    """
    Reads and cleans the Excel file. Yields log messages and the
    final DataFrame as ('result', df).
    """
    try:
        all_cleaned_dfs = []
        with pd.ExcelFile(excel_path) as xls:
            sheet_names = xls.sheet_names
            yield f"📋 Sheets found: {sheet_names}"
            
            sheets_to_process = sheet_names[1:] if len(sheet_names) > 1 else sheet_names
            
            for sheet in sheets_to_process:
                yield f"  📄 Processing sheet '{sheet}'..."
                df = pd.read_excel(xls, sheet_name=sheet)
                
                if df.empty:
                    yield f"    - Sheet '{sheet}' is empty, skipping."
                    continue
                
                df.dropna(how='all', inplace=True)
                if df.empty: continue
                    
                df.columns = [str(col).strip().upper() for col in df.columns]
                if 'STENCILS' in df.columns: df.rename(columns={'STENCILS': 'STENCIL'}, inplace=True)
                
                yield f"    - Found {len(df)} rows in '{sheet}'"
                all_cleaned_dfs.append(df)
        
        if not all_cleaned_dfs:
            yield "❌ No valid data found in sheets."
            yield ('result', None)
            return
            
        combined_df = pd.concat(all_cleaned_dfs, ignore_index=True)
        yield f" consolidating {len(combined_df)} total rows..."
        
        final_df = pd.DataFrame()
        column_mapping = {
            "STENCIL": "stencil", "ORIENTATION": "orientation", "INVOICE #": "invoice_number",
            "CONE SIZE": "cone_size", "# OF LINES": "number_of_lines", "MISC. INFO": "misc_info",
            "DATE": "date_of_inventory", "SILKSCREEN": "silkscreen"
        }
        
        for excel_col, db_col in column_mapping.items():
            if excel_col in combined_df.columns:
                # Apply specific cleaning based on the column
                if db_col == 'orientation':
                    # Standardize orientation: only 'HRZ', 'VERT', or None are allowed
                    final_df[db_col] = combined_df[excel_col].apply(
                        lambda x: str(x).strip().upper() if pd.notna(x) and str(x).strip() != '' else None
                    )
                    # Map common variations to the standard values
                    orientation_map = {'HORIZONTAL': 'HRZ', 'VERTICAL': 'VERT'}
                    final_df[db_col] = final_df[db_col].replace(orientation_map)
                    # Set any value that is not HRZ or VERT to None
                    final_df[db_col] = final_df[db_col].apply(
                        lambda x: x if x in ['HRZ', 'VERT'] else None
                    )
                elif db_col == 'date_of_inventory':
                    # Convert dates to strings to avoid JSON serialization issues
                    final_df[db_col] = pd.to_datetime(combined_df[excel_col], errors='coerce').apply(
                        lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else None
                    )
                else:
                    # For all other columns, just convert to string and strip whitespace
                    final_df[db_col] = combined_df[excel_col].apply(
                        lambda x: str(x).strip() if pd.notna(x) and str(x).strip() != '' else None
                    )
            else:
                final_df[db_col] = None # Add missing columns with None
        
        yield "✅ Data cleaning complete."
        yield ('result', final_df)
        
    except Exception as e:
        yield f"❌ Error while reading Excel file: {e}"
        yield ('result', None)

def list_available_files():
    """
    Liste les fichiers Excel disponibles dans chaque entrepôt.
    """
    print("📋 Fichiers Excel disponibles:")
    print("="*50)
    
    for warehouse, config in WAREHOUSE_CONFIG.items():
        warehouse_folder = f"data/warehouses/{warehouse}"
        excel_path = find_excel_file(warehouse_folder, warehouse)
        
        if excel_path and os.path.exists(excel_path):
            file_size = os.path.getsize(excel_path)
            mod_time = datetime.fromtimestamp(os.path.getmtime(excel_path))
            print(f"✅ {warehouse} ({config['name']}): {excel_path}")
            print(f"   Taille: {file_size:,} bytes, Modifié: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print(f"❌ {warehouse} ({config['name']}): Aucun fichier Excel trouvé dans {warehouse_folder}")
        print()
