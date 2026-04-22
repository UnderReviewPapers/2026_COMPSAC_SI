import os
from pymongo import MongoClient
from bson import ObjectId
from .mongodb_dataframe_builder import AtomicServiceDataFrameBuilder

MONGO_HOST = os.environ.get("MONGO_HOST", "localhost")
MONGO_PORT = int(os.environ.get("MONGO_PORT", 27017))
MONGO_DB   = os.environ.get("MONGO_DB", "ds-designer_db")

#connesione a mongodb
#client = MongoClient("mongodb://mongo:27017/")
client = MongoClient(
    host=MONGO_HOST,
    port=MONGO_PORT,
    serverSelectionTimeoutMS=5000
)

db = client[MONGO_DB]

#definizione collections
atomic_services_collection = db['atomic_services']
atomic_df = db['atomic_df']
atomic_df_overview = db['atomic_df_overview']
atomic_df_params = db['atomic_df_params']
cpps_collection = db['cpps']
cppn_collection = db['cppn']
bpmn_collection = db['bpmn']
openapi_collection = db['openapi']
rbac_collection = db['rbac']


class MongoDBHandler:

    @staticmethod
    def save_atomic(data):
        required_fields = ['diagram_id', 'task_id', 'name', 'atomic_type', 'input', 'output', 'method', 'url', 'owner']
        missing = [f for f in required_fields if f not in data]
        if missing:
            return {'error': f'Missing fields: {", ".join(missing)}'}, 400

        try:
            diagram_id = ObjectId(data['diagram_id'])
        except Exception:
            return {'error': 'Invalid diagram ID'}, 400

        diagram = bpmn_collection.find_one({'_id': diagram_id})
        if not diagram:
            return {'error': 'Diagram not found'}, 404

        try:
            # Salva atomic nel DB
            result = atomic_services_collection.update_one(
                {'task_id': data['task_id']},
                {
                    '$set': {
                        'diagram_id': str(diagram_id),
                        'name': data['name'],
                        'atomic_type': data['atomic_type'],
                        'input': data['input'],    # <-- già con i tipi
                        'output': data['output'],  # <-- già con i tipi
                        'method': data['method'],
                        'url': data['url'],
                        'owner': data['owner']
                    }
                },
                upsert=True
            )
            created = result.upserted_id is not None

            # Ricarica documento salvato
            doc = atomic_services_collection.find_one({'task_id': data['task_id']}, {'_id': 0})
            doc['diagram_id'] = str(doc['diagram_id'])

            combined_df = AtomicServiceDataFrameBuilder.from_document(doc)
            MongoDBHandler.persist_atomic_dataframes(combined_df, mode='nested')

            return {'status': 'ok', 'created': created}, 200

        except Exception as e:
            return {'error': str(e)}, 500


    @staticmethod
    def persist_atomic_dataframes(df, mode='nested'):
        """
        Salva il dataframe unico su MongoDB.

        mode:
        - 'nested': salva tutto come un array di record in un unico documento
        - 'separate': salva in una collection separata per riga
        """
        if df.empty:
            print("DataFrame is empty, skipping persistence.")
            return

        task_id = df['task_id'].iloc[0]
        records = df.to_dict(orient='records')

        if mode == 'nested':
            doc = {'task_id': task_id, 'data': records}
            atomic_df.replace_one({'task_id': task_id}, doc, upsert=True)
            print(f"Saved combined DataFrame as nested document for task_id: {task_id}")

        elif mode == 'separate':
            atomic_df.delete_many({'task_id': task_id})  # clean old data
            atomic_df.insert_many(records)
            print(f"Saved combined DataFrame as separate documents for task_id: {task_id}")

        else:
            raise ValueError("Unknown mode: choose from 'nested' or 'separate'")


    @staticmethod
    def save_cppn(data):
        required_fields = [
            'diagram_id',
            'group_id',
            'name',
            'description',
            'workflow_type',
            'components',
            'actors',
            'gdpr_map',
            'business_goal'
        ]

        missing = [f for f in required_fields if f not in data]
        if missing:
            return {'error': f'Missing fields: {", ".join(missing)}'}, 400

        if not isinstance(data['actors'], list):
            return {'error': 'Field "actors" must be a list'}, 400

        if not isinstance(data['gdpr_map'], dict):
            return {'error': 'Field "gdpr_map" must be a JSON object'}, 400

        try:
            diagram_id = ObjectId(data['diagram_id'])
        except Exception:
            return {'error': 'Invalid diagram ID'}, 400

        diagram = bpmn_collection.find_one({'_id': diagram_id})
        if not diagram:
            return {'error': 'Diagram not found'}, 404

        try:
            doc = {
                "group_type": "CPPN",
                'diagram_id': str(diagram_id),
                'group_id': data['group_id'],
                'name': data['name'],
                'description': data['description'],
                'workflow_type': data['workflow_type'],
                'actors': data['actors'],
                'gdpr_map': data['gdpr_map'],
                'business_goal' : data['business_goal']
            }

            # Unisco atomic_services + nested_cpps in components
            doc['components'] =  data['components']

            #salvo grafo connessione components se presente
            if 'workflow' in data:
                doc['workflow'] = data['workflow']

            result = cppn_collection.update_one(
                {'group_id': data['group_id']},
                {'$set': doc},
                upsert=True
            )

            created = result.upserted_id is not None
            return {'status': 'ok', 'created': created}, 200

        except Exception as e:
            return {'error': str(e)}, 500

    @staticmethod
    def save_cpps(data):
        required_fields = [
            'diagram_id',
            'group_id',
            'name',
            'description',
            'workflow_type',
            'components',
            'owner',
            'endpoints'
        ]

        missing = [f for f in required_fields if f not in data]
        if missing:
            return {'error': f'Missing fields: {", ".join(missing)}'}, 400

        try:
            diagram_id = ObjectId(data['diagram_id'])
        except Exception:
            return {'error': 'Invalid diagram ID'}, 400

        diagram = bpmn_collection.find_one({'_id': diagram_id})
        if not diagram:
            return {'error': 'Diagram not found'}, 404

        try:
            doc = {
                "group_type": "CPPS",
                "diagram_id": str(diagram_id),
                "group_id": data['group_id'],
                "name": data['name'],
                "description": data['description'],
                "workflow_type": data['workflow_type'],
                "owner": data['owner'],
                "endpoints": data['endpoints'],
                "components": data['components']
            }

            if 'workflow' in data:
                doc['workflow'] = data['workflow']


            result = cpps_collection.update_one(
                {'group_id': data['group_id']},
                {'$set': doc},
                upsert=True
            )

            created = result.upserted_id is not None
            return {'status': 'ok', 'created': created}, 200

        except Exception as e:
            return {'error': str(e)}, 500

    @staticmethod
    def save_openapi_documentation(openapi_doc):
        openapi_collection.insert_one(openapi_doc)
        return {"message": "OpenAPI documentation saved"}, 201
