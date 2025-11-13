(config as record) as function =>
  (t as table) as table =>
    let
      prefix = config[prefix],
      exceptions = if Record.HasFields(config, "exceptions") then config[exceptions] else {},
      renamer = (name as text) as text =>
        if List.Contains(List.Transform(exceptions, each Text.EndsWith(name, _)), true) then
          name
        else if prefix = null or prefix = "" then
          name
        else
          prefix & " " & name
    in
      Table.TransformColumnNames(t, renamer)