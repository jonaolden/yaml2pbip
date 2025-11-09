(t as table) as table 
  let
    renamer = (name as text) as text =>
      if Text.EndsWith(name, "_ID") then name
      else Text.Proper(Text.Replace(name, "_", " "))
  in
    Table.TransformColumnNames(t, renamer)
