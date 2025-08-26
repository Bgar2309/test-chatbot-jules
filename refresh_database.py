import os
import pandas as pd
from supabase import create_client, Client
from dotenv import load_dotenv
import sys
from datetime import datetime
from pathlib import Path
import glob
import numpy as np

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
    Trouve automatiquement le fichier Excel dans le dossier de l'entrepôt.
    Cherche des patterns comme:
    - NJ_STENCIL_INVENTORY.xlsx
    - NJ STENCIL INVENTORY.xlsx  
    - NJ STENCIL INVENTORY (2).xlsx
    etc.
    """
    possible_patterns = [
        f"{warehouse_code}_STENCIL_INVENTORY.xlsx",
        f"{warehouse_code} STENCIL INVENTORY.xlsx",
        f"{warehouse_code} STENCIL INVENTORY (2).xlsx",
        f"{warehouse_code} STENCIL INVENTORY (3).xlsx",
        f"{warehouse_code}_inventory.xlsx",
        f"{warehouse_code}_INVENTORY.xlsx"
    ]
    
    for pattern in possible_patterns:
        full_path = os.path.join(warehouse_folder, pattern)
        if os.path.exists(full_path):
            print(f"📄 Fichier Excel trouvé: {full_path}")
            return full_path
    
    # Si aucun pattern spécifique trouvé, chercher n'importe quel .xlsx
    xlsx_files = glob.glob(os.path.join(warehouse_folder, "*.xlsx"))
    if xlsx_files:
        print(f"📄 Fichier Excel détecté automatiquement: {xlsx_files[0]}")
        return xlsx_files[0]
    
    return None

def create_directory_structure():
    """
    Crée la structure de dossiers si elle n'existe pas.
    """
    directories = [
        "data",
        "data/warehouses",
        "data/warehouses/NJ",
        "data/warehouses/CA", 
        "data/warehouses/TX",
        "data/exports"
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"📁 Dossier créé/vérifié: {directory}")

def refresh_inventory_database(warehouse_code=None):
    """
    Efface et recrée les données pour un ou tous les entrepôts.
    
    Args:
        warehouse_code (str): Code de l'entrepôt (NJ, CA, TX) ou None pour tous
    """
    load_dotenv()
    
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        print("❌ Erreur: Variables d'environnement Supabase manquantes")
        return False
    
    try:
        supabase: Client = create_client(supabase_url, supabase_key)
        print(f"✅ Connexion à Supabase réussie")
        
        # Déterminer quels entrepôts traiter
        if warehouse_code:
            if warehouse_code.upper() not in WAREHOUSE_CONFIG:
                print(f"❌ Entrepôt '{warehouse_code}' non reconnu. Entrepôts disponibles: {list(WAREHOUSE_CONFIG.keys())}")
                return False
            warehouses_to_process = [warehouse_code.upper()]
        else:
            warehouses_to_process = list(WAREHOUSE_CONFIG.keys())
        
        print(f"🏭 Entrepôts à traiter: {warehouses_to_process}")
        
        success_count = 0
        for warehouse in warehouses_to_process:
            print(f"\n{'='*60}")
            print(f"🏭 Traitement de l'entrepôt {warehouse} ({WAREHOUSE_CONFIG[warehouse]['name']})")
            print(f"{'='*60}")
            
            config = WAREHOUSE_CONFIG[warehouse]
            warehouse_folder = f"data/warehouses/{warehouse}"
            csv_path = config["csv_export"]
            
            # Chercher automatiquement le fichier Excel
            excel_path = find_excel_file(warehouse_folder, warehouse)
            
            # Vérifier que le fichier Excel existe
            if not excel_path:
                print(f"⚠️ Aucun fichier Excel trouvé dans: {warehouse_folder}")
                print(f"   Veuillez placer un fichier Excel de {warehouse} dans ce dossier.")
                print(f"   Noms acceptés: {warehouse}_STENCIL_INVENTORY.xlsx, {warehouse} STENCIL INVENTORY.xlsx, etc.")
                continue
            
            # 1. Lire et nettoyer le fichier Excel
            print(f"📊 Lecture du fichier Excel: {excel_path}")
            df = read_and_clean_excel(excel_path)
            
            if df is None or df.empty:
                print(f"❌ Aucune donnée trouvée dans {excel_path}")
                continue
                
            # 2. Ajouter la colonne warehouse
            df['warehouse'] = warehouse
            
            print(f"📈 {len(df)} entrées trouvées pour l'entrepôt {warehouse}")
            
            # 3. Sauvegarder en CSV (optionnel, pour backup)
            df_export = df.copy()
            df_export.to_csv(csv_path, index=False)
            print(f"💾 Export CSV sauvegardé: {csv_path}")
            
            # 4. Vider complètement la table pour cet entrepôt
            print(f"🗑️ Suppression des données existantes pour {warehouse}...")
            try:
                delete_result = supabase.table("inventory").delete().eq("warehouse", warehouse).execute()
                print(f"✅ Données supprimées pour {warehouse}")
            except Exception as e:
                print(f"⚠️ Erreur lors de la suppression (probablement normal si première fois): {e}")
            
            # 5. Insérer les nouvelles données par chunks
            chunk_size = 100
            total_chunks = (len(df) + chunk_size - 1) // chunk_size
            
            print(f"📤 Upload des données en {total_chunks} chunks...")
            
            inserted_count = 0
            for i in range(0, len(df), chunk_size):
                chunk = df.iloc[i:i + chunk_size]
                chunk_records = chunk.to_dict(orient="records")
                
                # Nettoyer les valeurs NaN pour Supabase et convertir les types problématiques
                for record in chunk_records:
                    for key, value in record.items():
                        if pd.isna(value) or value is None:
                            record[key] = None
                        # Convertir les dates/timestamps en strings
                        elif isinstance(value, (pd.Timestamp, datetime, np.datetime64)):
                            try:
                                if hasattr(value, 'strftime'):
                                    record[key] = value.strftime('%Y-%m-%d')
                                else:
                                    record[key] = str(value).split('T')[0] if 'T' in str(value) else str(value)
                            except:
                                record[key] = str(value) if value != '' else None
                        # Convertir les nombres numpy en types Python natifs
                        elif isinstance(value, (np.integer, np.floating)):
                            record[key] = value.item()
                        # Convertir les booléens numpy
                        elif isinstance(value, np.bool_):
                            record[key] = bool(value)
                        # Autres types avec strftime (dates diverses)
                        elif hasattr(value, 'strftime'):
                            try:
                                record[key] = value.strftime('%Y-%m-%d')
                            except:
                                record[key] = str(value) if value != '' else None
                        # S'assurer que les strings vides deviennent None
                        elif isinstance(value, str) and value.strip() == '':
                            record[key] = None
                
                try:
                    # Insérer le chunk
                    result = supabase.table("inventory").insert(chunk_records).execute()
                    inserted_count += len(chunk_records)
                    print(f"  ✅ Chunk {(i//chunk_size)+1}/{total_chunks} uploadé ({len(chunk_records)} entrées)")
                except Exception as e:
                    print(f"  ❌ Erreur chunk {(i//chunk_size)+1}: {e}")
                    continue
            
            # 6. Vérification finale
            try:
                count_result = supabase.table("inventory").select("id", count="exact").eq("warehouse", warehouse).execute()
                print(f"🔍 Vérification: {count_result.count} entrées dans la base pour {warehouse}")
                
                if count_result.count == len(df):
                    print(f"🎉 Mise à jour réussie pour {warehouse}!")
                    success_count += 1
                else:
                    print(f"⚠️ Nombre d'entrées différent pour {warehouse}: attendu {len(df)}, trouvé {count_result.count}")
            except Exception as e:
                print(f"❌ Erreur lors de la vérification: {e}")
        
        print(f"\n{'='*60}")
        print(f"🎯 RÉSUMÉ FINAL")
        print(f"{'='*60}")
        print(f"✅ {success_count}/{len(warehouses_to_process)} entrepôts mis à jour avec succès")
        
        return success_count > 0
        
    except Exception as e:
        print(f"❌ Erreur générale lors de la mise à jour: {e}")
        return False

def read_and_clean_excel(excel_path):
    """
    Lit et nettoie le fichier Excel.
    """
    FINAL_COLUMNS = [
        "STENCIL", "ORIENTATION", "INVOICE #", "CONE SIZE", 
        "# OF LINES", "MISC. INFO", "DATE", "SILKSCREEN"
    ]
    
    try:
        all_cleaned_dfs = []
        
        with pd.ExcelFile(excel_path) as xls:
            sheet_names = xls.sheet_names
            print(f"📋 Feuilles trouvées: {sheet_names}")
            
            if len(sheet_names) <= 1:
                print("⚠️ Une seule feuille trouvée, traitement de la première feuille")
                sheets_to_process = sheet_names
            else:
                sheets_to_process = sheet_names[1:]  # Skip first sheet
                print(f"📋 Traitement des feuilles: {sheets_to_process}")
            
            for sheet in sheets_to_process:
                print(f"  📄 Traitement de '{sheet}'...")
                df = pd.read_excel(xls, sheet_name=sheet)
                
                if df.empty:
                    print(f"    ⚠️ Feuille '{sheet}' vide, ignorée")
                    continue
                
                # Nettoyer la DataFrame
                df.dropna(how='all', inplace=True)
                if df.empty:
                    continue
                    
                # Standardiser les noms de colonnes
                df.columns = [str(col).strip().upper() for col in df.columns]
                
                # Renommer STENCILS en STENCIL si nécessaire
                if 'STENCILS' in df.columns:
                    df.rename(columns={'STENCILS': 'STENCIL'}, inplace=True)
                
                print(f"    ✅ {len(df)} lignes trouvées dans '{sheet}'")
                all_cleaned_dfs.append(df)
        
        if not all_cleaned_dfs:
            print("❌ Aucune donnée valide trouvée")
            return None
            
        # Combiner toutes les DataFrames
        combined_df = pd.concat(all_cleaned_dfs, ignore_index=True)
        
        # Créer DataFrame finale avec colonnes standardisées
        final_df = pd.DataFrame()
        column_mapping = {
            "STENCIL": "stencil",
            "ORIENTATION": "orientation", 
            "INVOICE #": "invoice_number",
            "CONE SIZE": "cone_size",
            "# OF LINES": "number_of_lines",
            "MISC. INFO": "misc_info",
            "DATE": "date_of_inventory",
            "SILKSCREEN": "silkscreen"
        }
        
        for excel_col, db_col in column_mapping.items():
            if excel_col in combined_df.columns:
                final_df[db_col] = combined_df[excel_col]
                
                # Nettoyage spécifique par colonne
                if db_col == 'date_of_inventory':
                    # Convertir les dates en strings pour éviter les problèmes JSON
                    final_df[db_col] = final_df[db_col].apply(
                        lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) and hasattr(x, 'strftime') 
                        else str(x) if pd.notna(x) and x != '' 
                        else None
                    )
                elif db_col == 'orientation':
                    # Nettoyer l'orientation : seulement HRZ, VER ou None
                    final_df[db_col] = final_df[db_col].apply(
                        lambda x: str(x).strip().upper() if pd.notna(x) and str(x).strip() != '' 
                        else None
                    )
                    # Vérifier que les valeurs sont valides
                    final_df[db_col] = final_df[db_col].apply(
                        lambda x: x if x in ['HRZ', 'VER'] else None
                    )
                else:
                    # Pour les autres colonnes, convertir les strings vides en None
                    final_df[db_col] = final_df[db_col].apply(
                        lambda x: str(x).strip() if pd.notna(x) and str(x).strip() != '' 
                        else None
                    )
            else:
                final_df[db_col] = None
                print(f"    ⚠️ Colonne '{excel_col}' manquante, remplie avec None")
        
        print(f"✅ Nettoyage terminé: {len(final_df)} entrées au total")
        
        # Rapport de nettoyage
        print(f"📊 Statistiques de nettoyage:")
        print(f"   - Orientations HRZ: {(final_df['orientation'] == 'HRZ').sum()}")
        print(f"   - Orientations VER: {(final_df['orientation'] == 'VER').sum()}")  
        print(f"   - Orientations vides: {final_df['orientation'].isna().sum()}")
        print(f"   - Avec dates: {final_df['date_of_inventory'].notna().sum()}")
        print(f"   - Sans dates: {final_df['date_of_inventory'].isna().sum()}")
        
        return final_df
        
    except Exception as e:
        print(f"❌ Erreur lors de la lecture Excel: {e}")
        return None

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

if __name__ == "__main__":
    print("🏭 Multi-Warehouse Inventory Database Refresh Tool")
    print("="*60)
    
    # Créer la structure de dossiers
    create_directory_structure()
    
    if len(sys.argv) > 1:
        command = sys.argv[1].upper()
        
        if command == "LIST":
            list_available_files()
        elif command in WAREHOUSE_CONFIG:
            refresh_inventory_database(command)
        else:
            print(f"❌ Commande/Entrepôt non reconnu: {command}")
            print(f"Entrepôts disponibles: {list(WAREHOUSE_CONFIG.keys())}")
            print("Ou utilisez 'LIST' pour voir les fichiers disponibles")
    else:
        print("Usage:")
        print("  python refresh_database.py NJ     # Met à jour seulement New Jersey")
        print("  python refresh_database.py CA     # Met à jour seulement California") 
        print("  python refresh_database.py TX     # Met à jour seulement Texas")
        print("  python refresh_database.py LIST   # Liste les fichiers disponibles")
        print("  python refresh_database.py        # Met à jour tous les entrepôts")
        print()
        
        # Par défaut, traiter tous les entrepôts
        refresh_inventory_database()