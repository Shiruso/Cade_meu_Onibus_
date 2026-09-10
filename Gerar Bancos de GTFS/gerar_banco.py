import sqlite3
import pandas as pd
import os
import zipfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

def processar_gtfs():
    zip_path = filedialog.askopenfilename(title="Selecione o arquivo gtfs.zip", filetypes=[("Zip files", "*.zip")])
    if not zip_path: return
    output_dir = os.path.dirname(zip_path)
    db_path = os.path.join(output_dir, "gtfs_rio.db")
    if os.path.exists(db_path): os.remove(db_path)

    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            print("Criando tabelas padrão Room...")
            # RouteEntity
            cursor.execute("CREATE TABLE IF NOT EXISTS `routes` (`routeId` TEXT NOT NULL, `routeShortName` TEXT NOT NULL, `isImported` INTEGER NOT NULL, PRIMARY KEY(`routeId`))")
            # StopEntity
            cursor.execute("CREATE TABLE IF NOT EXISTS `stops` (`stopId` TEXT NOT NULL, `stopName` TEXT NOT NULL, `stopLat` REAL NOT NULL, `stopLon` REAL NOT NULL, PRIMARY KEY(`stopId`))")
            # TripEntity
            cursor.execute("CREATE TABLE IF NOT EXISTS `trips` (`tripId` TEXT NOT NULL, `routeId` TEXT NOT NULL, `directionId` INTEGER NOT NULL, `shapeId` TEXT NOT NULL, `tripHeadsign` TEXT NOT NULL, PRIMARY KEY(`tripId`))")
            # StopTimeEntity
            cursor.execute("CREATE TABLE IF NOT EXISTS `stop_times` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `tripId` TEXT NOT NULL, `stopId` TEXT NOT NULL, `stopSequence` INTEGER NOT NULL)")
            # ShapePointEntity
            cursor.execute("CREATE TABLE IF NOT EXISTS `shapes` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `shapeId` TEXT NOT NULL, `lat` REAL NOT NULL, `lon` REAL NOT NULL, `sequence` INTEGER NOT NULL)")
            # FrequencyEntity
            cursor.execute("CREATE TABLE IF NOT EXISTS `frequencies` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `tripId` TEXT NOT NULL, `startTime` TEXT NOT NULL, `endTime` TEXT NOT NULL, `headwaySecs` INTEGER NOT NULL)")

            def ler_zip(nome):
                try:
                    with z.open(nome) as f: return pd.read_csv(f, dtype=str)
                except KeyError: return None

            print("Importando e otimizando dados...")
            # Routes
            df = ler_zip("routes.txt")
            if df is not None:
                df[['route_id', 'route_short_name']].rename(columns={'route_id':'routeId', 'route_short_name':'routeShortName'}).assign(isImported=1).to_sql('routes', conn, if_exists='append', index=False)

            # Stops
            df = ler_zip("stops.txt")
            if df is not None:
                df[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']].rename(columns={'stop_id':'stopId', 'stop_name':'stopName', 'stop_lat':'stopLat', 'stop_lon':'stopLon'}).to_sql('stops', conn, if_exists='append', index=False)

            # Trips e Filtragem (Pega apenas 1 trip por linha/sentido para o banco ficar leve)
            df_trips = ler_zip("trips.txt")
            if df_trips is not None:
                trips_unicas = df_trips.drop_duplicates(subset=['route_id', 'direction_id'])
                trips_unicas[['trip_id', 'route_id', 'direction_id', 'shape_id', 'trip_headsign']].rename(columns={'trip_id':'tripId', 'route_id':'routeId', 'direction_id':'directionId', 'shape_id':'shapeId', 'trip_headsign':'tripHeadsign'}).to_sql('trips', conn, if_exists='append', index=False)
                
                # Stop Times
                df_st = ler_zip("stop_times.txt")
                if df_st is not None:
                    df_st[df_st['trip_id'].isin(trips_unicas['trip_id'])][['trip_id', 'stop_id', 'stop_sequence']].rename(columns={'trip_id':'tripId', 'stop_id':'stopId', 'stop_sequence':'stopSequence'}).to_sql('stop_times', conn, if_exists='append', index=False)

                # Shapes
                df_sh = ler_zip("shapes.txt")
                if df_sh is not None:
                    shape_ids = trips_unicas['shape_id'].unique()
                    df_sh[df_sh['shape_id'].isin(shape_ids)][['shape_id', 'shape_pt_lat', 'shape_pt_lon', 'shape_pt_sequence']].rename(columns={'shape_id':'shapeId', 'shape_pt_lat':'lat', 'shape_pt_lon':'lon', 'shape_pt_sequence':'sequence'}).to_sql('shapes', conn, if_exists='append', index=False)

            # Frequencies
            df = ler_zip("frequencies.txt")
            if df is not None:
                df[['trip_id', 'start_time', 'end_time', 'headway_secs']].rename(columns={'trip_id':'tripId', 'start_time':'startTime', 'end_time':'endTime', 'headway_secs':'headwaySecs'}).to_sql('frequencies', conn, if_exists='append', index=False)

            print("Criando índices oficiais do Room...")
            cursor.execute("CREATE INDEX IF NOT EXISTS `index_routes_routeShortName` ON `routes` (`routeShortName`)")
            cursor.execute("CREATE INDEX IF NOT EXISTS `index_trips_routeId` ON `trips` (`routeId`)")
            cursor.execute("CREATE INDEX IF NOT EXISTS `index_stop_times_tripId` ON `stop_times` (`tripId`)")
            cursor.execute("CREATE INDEX IF NOT EXISTS `index_shapes_shapeId` ON `shapes` (`shapeId`)")
            cursor.execute("CREATE INDEX IF NOT EXISTS `index_frequencies_tripId` ON `frequencies` (`tripId`)")

            # Tabela de Identidade (Obrigatória para o Room não rejeitar o arquivo)
            cursor.execute("CREATE TABLE IF NOT EXISTS room_master_table (id INTEGER PRIMARY KEY, identity_hash TEXT)")
            # Nota: O hash será inserido automaticamente pelo Android na primeira execução se usarmos o fallback
            
            conn.execute("VACUUM")
            conn.commit()
            conn.close()
            
            size = os.path.getsize(db_path) / (1024*1024)
            messagebox.showinfo("Sucesso", f"Banco 'Android-Ready' Gerado!\nTamanho: {size:.2f} MB\nUpe este arquivo no seu GitHub.")

    except Exception as e:
        messagebox.showerror("Erro", str(e))

# Interface
app = tk.Tk(); app.title("Gerador GTFS Android"); app.geometry("300x150")
ttk.Button(app, text="Selecionar gtfs.zip e Criar Banco", command=processar_gtfs).pack(expand=True)
app.mainloop()
