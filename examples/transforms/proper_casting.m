each 
  let
    renamer = (name as text) as text =>
      if Text.EndsWith(name, "_KEY") then name
      else Text.Proper(Text.Replace(name, "_", " "))
  in
    Table.TransformColumnNames(t, renamer)

