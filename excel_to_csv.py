import pandas as pd

def convert_excel_to_csv(excel_path, csv_path):
    """
    Reads all sheets from an Excel file (except the first one),
    concatenates them, and saves the result to a single CSV file.
    """
    try:
        # Use pd.ExcelFile to be able to access sheet names
        with pd.ExcelFile(excel_path) as xls:
            sheet_names = xls.sheet_names

            # The user wants to skip the first sheet ("A")
            if len(sheet_names) > 1:
                sheets_to_process = sheet_names[1:]
                print(f"Found sheets: {sheet_names}")
                print(f"Processing sheets: {sheets_to_process}")
            else:
                print("Only one sheet found, nothing to process after skipping the first one.")
                return

            # Read all subsequent sheets into a list of DataFrames
            df_list = [pd.read_excel(xls, sheet_name=sheet) for sheet in sheets_to_process]

            if not df_list:
                print("No dataframes to concatenate.")
                return

            # Concatenate all DataFrames into one
            combined_df = pd.concat(df_list, ignore_index=True)

            # Save the combined DataFrame to CSV
            combined_df.to_csv(csv_path, index=False)
            print(f"Successfully combined {len(sheets_to_process)} sheets and saved to '{csv_path}'")

    except FileNotFoundError:
        print(f"Error: The file '{excel_path}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    convert_excel_to_csv("NJ STENCIL INVENTORY.xlsx", "inventory.csv")
