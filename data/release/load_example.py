import pandas as pd
df = pd.read_csv("sample_1000_rows.csv")
print("rows:", len(df))
print(df["provenance"].value_counts())
print(df.head())
