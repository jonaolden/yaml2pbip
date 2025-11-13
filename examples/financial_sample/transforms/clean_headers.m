(Sheet as table) as table =>
let
    CleanedColumns = Table.TransformColumnNames(Sheet, Text.Trim)
in
    CleanedColumns
