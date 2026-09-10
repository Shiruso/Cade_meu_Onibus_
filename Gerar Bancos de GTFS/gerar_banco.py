import sqlite3, pandas as pd, os, zipfile, tkinter as tk
from tkinter import filedialog, messagebox, ttk

def processar_gtfs():
    zip_path = filedialog.askopenfilename(title="Selecione o arquivo gtfs.zip", filetypes=[("Zip files", "*.zip")])
    if not zip_path: return
    db_path = os.path.join(os.path.dirname(zip_path), "gtfs_rio.db")
    if os.path.exists(db_path): os.remove(db_path)

    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            conn = sqlite3.connect(db_path); cursor = conn.cursor()
            # Esquema EXATO exigido pelo Android Room v13
            cursor.execute("CREATE TABLE IF NOT EXISTS `routes` (`routeId` TEXT NOT NULL, `routeShortName` TEXT NOT NULL, `isImported` INTEGER NOT NULL, PRIMARY KEY(`routeId`))")
            cursor.execute("CREATE TABLE IF NOT EXISTS `stops` (`stopId` TEXT NOT NULL, `stopName` TEXT NOT NULL, `stopLat` REAL NOT NULL, `stopLon` REAL NOT NULL, PRIMARY KEY(`stopId`))")
            cursor.execute("CREATE TABLE IF NOT EXISTS `trips` (`tripId` TEXT NOT NULL, `routeId` TEXT NOT NULL, `directionId` INTEGER NOT NULL, `shapeId` TEXT NOT NULL, `tripHeadsign` TEXT NOT NULL, PRIMARY KEY(`tripId`))")
            cursor.execute("CREATE TABLE IF NOT EXISTS `stop_times` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `tripId` TEXT NOT NULL, `stopId` TEXT NOT NULL, `stopSequence` INTEGER NOT NULL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS `shapes` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `shapeId` TEXT NOT NULL, `lat` REAL NOT NULL, `lon` REAL NOT NULL, `sequence` INTEGER NOT NULL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS `frequencies` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `tripId` TEXT NOT NULL, `startTime` TEXT NOT NULL, `endTime` TEXT NOT NULL, `headwaySecs` INTEGER NOT NULL)")

            def ler_zip(n):
                with z.open(n) as f: return pd.read_csv(f, dtype=str)

            print("Importando dados..."); df = ler_zip("routes.txt")
            df[['route_id', 'route_short_name']].rename(columns={'route_id':'routeId', 'route_short_name':'routeShortName'}).assign(isImported=1).to_sql('routes', conn, if_exists='append', index=False)
            
            df = ler_zip("stops.txt")
            df[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']].rename(columns={'stop_id':'stopId', 'stop_name':'stopName', 'stop_lat':'stopLat', 'stop_lon':'stopLon'}).to_sql('stops', conn, if_exists='append', index=False)

            df_trips = ler_zip("trips.txt")
            trips_unicas = df_trips.drop_duplicates(subset=['route_id', 'direction_id'])
            trips_unicas[['trip_id', 'route_id', 'direction_id', 'shape_id', 'trip_headsign']].rename(columns={'trip_id':'tripId', 'route_id':'routeId', 'direction_id':'directionId', 'shape_id':'shapeId', 'trip_headsign':'tripHeadsign'}).to_sql('trips', conn, if_exists='append', index=False)
            
            df_st = ler_zip("stop_times.txt")
            df_st[df_st['trip_id'].isin(trips_unicas['trip_id'])][['trip_id', 'stop_id', 'stop_sequence']].rename(columns={'trip_id':'tripId', 'stop_id':'stopId', 'stop_sequence':'stopSequence'}).to_sql('stop_times', conn, if_exists='append', index=False)

            df_sh = ler_zip("shapes.txt")
            shape_ids = trips_unicas['shape_id'].unique()
            df_sh[df_sh['shape_id'].isin(shape_ids)][['shape_id', 'shape_pt_lat', 'shape_pt_lon', 'shape_pt_sequence']].rename(columns={'shape_id':'shapeId', 'shape_pt_lat':'lat', 'shape_pt_lon':'lon', 'shape_pt_sequence':'sequence'}).to_sql('shapes', conn, if_exists='append', index=False)

            cursor.execute("CREATE INDEX IF NOT EXISTS `index_routes_routeShortName` ON `routes` (`routeShortName`)")
            cursor.execute("CREATE INDEX IF NOT EXISTS `index_trips_routeId` ON `trips` (`routeId`)")
            cursor.execute("CREATE INDEX IF NOT EXISTS `index_stop_times_tripId` ON `stop_times` (`tripId`)")
            cursor.execute("CREATE INDEX IF NOT EXISTS `index_shapes_shapeId` ON `shapes` (`shapeId`)")
            
            conn.execute("VACUUM"); conn.commit(); conn.close()
            messagebox.showinfo("Sucesso", "Banco v13 Gerado!"); 
    except Exception as e: messagebox.showerror("Erro", str(e))

app = tk.Tk(); app.title("Gerador GTFS v13"); app.geometry("300x100")
ttk.Button(app, text="Criar Banco para o App", command=processar_gtfs).pack(expand=True); app.mainloop()
