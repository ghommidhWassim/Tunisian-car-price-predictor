import duckdb

con = duckdb.connect("cars.duckdb")
print(con.execute("SHOW TABLES").fetchdf())
print(con.execute("SELECT * FROM versions LIMIT 10").fetchdf())
