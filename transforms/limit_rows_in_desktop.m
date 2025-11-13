(maxRows as number) as function =>
  (t as table) as table =>
    Table.FirstN(t, maxRows)