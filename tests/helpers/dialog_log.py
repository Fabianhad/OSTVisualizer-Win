def records_for_shown_box(logs, box):
    title, text = box.call_args.args[1:3]
    shown = f"{title}: {text}"
    return [
        record
        for record in logs.records
        if record.getMessage().startswith(shown)
        or f"[shown: {shown}]" in record.getMessage()
    ]
