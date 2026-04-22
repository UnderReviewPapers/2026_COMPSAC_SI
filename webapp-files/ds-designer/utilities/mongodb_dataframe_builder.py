import pandas as pd

class AtomicServiceDataFrameBuilder:

    @staticmethod
    def from_document(doc):
        rows = []

        for param_name, param_type in doc.get('input', {}).items():
            rows.append({
                'task_id': doc['task_id'],
                'diagram_id': doc['diagram_id'],
                'name': doc['name'],
                'atomic_type': doc['atomic_type'],
                'method': doc['method'],
                'url': doc['url'],
                'owner': doc['owner'],
                'param_name': param_name,
                'param_type': param_type,
                'io_type': 'input'
            })

        for param_name, param_type in doc.get('output', {}).items():
            rows.append({
                'task_id': doc['task_id'],
                'diagram_id': doc['diagram_id'],
                'name': doc['name'],
                'atomic_type': doc['atomic_type'],
                'method': doc['method'],
                'url': doc['url'],
                'owner': doc['owner'],
                'param_name': param_name,
                'param_type': param_type,
                'io_type': 'output'
            })

        df = pd.DataFrame(rows)

        input_rows = df[df['io_type'] == 'input'][['param_name', 'param_type']].reset_index(drop=True)
        output_rows = df[df['io_type'] == 'output'][['param_name', 'param_type']].reset_index(drop=True)

        overview = df[['task_id', 'diagram_id', 'name', 'atomic_type', 'method', 'url', 'owner']].iloc[0].to_dict()

        wide_row = {**overview}
        for idx, row in input_rows.iterrows():
            wide_row[f'input_{idx+1}'] = row['param_name']
            wide_row[f'input_{idx+1}_type'] = row['param_type']
        for idx, row in output_rows.iterrows():
            wide_row[f'output_{idx+1}'] = row['param_name']
            wide_row[f'output_{idx+1}_type'] = row['param_type']

        # Creazione final DataFrame
        wide_df = pd.DataFrame([wide_row])

        return wide_df