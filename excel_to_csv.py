import pandas as pd

# Define the final list of columns that should be in the CSV.
# This ensures consistency and matches the database schema.
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

def clean_dataframe(df):
    """
    Cleans a single DataFrame by removing empty rows, standardizing
    column names, and renaming alternate column names.
    """
    # 1. Drop rows where all elements are NaN (empty rows)
    df.dropna(how='all', inplace=True)
    if df.empty:
        return df

    # 2. Standardize column names (uppercase and stripped whitespace)
    df.columns = [str(col).strip().upper() for col in df.columns]

    # 3. Rename 'STENCILS' to 'STENCIL' if it exists
    if 'STENCILS' in df.columns:
        df.rename(columns={'STENCILS': 'STENCIL'}, inplace=True)

    return df


def convert_excel_to_csv(excel_path, csv_path):
    """
    Reads all sheets from an Excel file (except the first one),
    cleans the data from each sheet, concatenates them, and saves
    the result to a single, clean CSV file.
    """
    try:
        all_cleaned_dfs = []
        with pd.ExcelFile(excel_path) as xls:
            sheet_names = xls.sheet_names

            if len(sheet_names) <= 1:
                print("Only one sheet found. No other sheets to process.")
                return

            sheets_to_process = sheet_names[1:]
            print(f"Found sheets: {sheet_names}")
            print(f"Skipping first sheet ('{sheet_names[0]}'). Processing: {sheets_to_process}")

            for sheet in sheets_to_process:
                print(f"  - Processing sheet: '{sheet}'")
                df = pd.read_excel(xls, sheet_name=sheet)

                if df.empty:
                    print(f"    ...sheet is empty. Skipping.")
                    continue

                cleaned_df = clean_dataframe(df)
                if not cleaned_df.empty:
                    all_cleaned_dfs.append(cleaned_df)

            if not all_cleaned_dfs:
                print("No data found in the sheets to process.")
                # Create an empty CSV with the correct headers
                pd.DataFrame(columns=FINAL_COLUMNS).to_csv(csv_path, index=False)
                return

            # Concatenate all cleaned DataFrames into one.
            # Pandas will align data based on column names.
            combined_df = pd.concat(all_cleaned_dfs, ignore_index=True)

            # Create a new DataFrame with only the desired columns in the correct order.
            # This will also add any missing columns (e.g., SILKSCREEN) with None.
            final_df = pd.DataFrame()
            for col in FINAL_COLUMNS:
                if col in combined_df.columns:
                    final_df[col] = combined_df[col]
                else:
                    final_df[col] = None # Add missing column with empty values

            final_df.to_csv(csv_path, index=False)

            print(f"\nSuccessfully combined and cleaned {len(all_cleaned_dfs)} sheets.")
            print(f"Saved to '{csv_path}' with {len(final_df)} rows and columns: {list(final_df.columns)}")

    except FileNotFoundError:
        print(f"Error: The file '{excel_path}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    convert_excel_to_csv("NJ STENCIL INVENTORY.xlsx", "inventory.csv")
