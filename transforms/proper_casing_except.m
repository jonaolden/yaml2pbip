(exceptions as list) as function =>
  (t as table) as table =>
    let
      renamer = (name as text) as text =>
        if List.Contains(List.Transform(exceptions, each Text.EndsWith(name, _)), true) then 
          name
        else 
          Text.Proper(Text.Replace(name, "_", " "))
    in
      Table.TransformColumnNames(t, renamer)