(CleanedColumns as table) as table =>
let
    // Convert text columns to proper data types
    ConvertedTypes = Table.TransformColumnTypes(CleanedColumns, {
        {"Segment", type text},
        {"Country", type text},
        {"Product", type text},
        {"Discount Band", type text},
        {"Units Sold", type number},
        {"Manufacturing Price", type number},
        {"Sale Price", type number},
        {"Gross Sales", Currency.Type},
        {"Discounts", Currency.Type},
        {"Sales", Currency.Type},
        {"COGS", Currency.Type},
        {"Profit", Currency.Type},
        {"Date", type datetime},
        {"Month Number", Int64.Type},
        {"Month Name", type text},
        {"Year", Int64.Type}
    })
in
    ConvertedTypes
