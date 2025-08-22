import pandas as pd

def convert_excel_to_csv(excel_path, csv_path):
    """
    Reads an Excel file and converts it to a CSV file.
    """
    try:
        df = pd.read_excel(excel_path)
        df.to_csv(csv_path, index=False)
        print(f"Successfully converted '{excel_path}' to '{csv_path}'")
    except FileNotFoundError:
        print(f"Error: The file '{excel_path}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    convert_excel_to_csv("NJ STENCIL INVENTORY.xlsx", "inventory.csv")
