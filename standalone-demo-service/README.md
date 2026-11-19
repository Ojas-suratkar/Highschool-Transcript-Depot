# standalone-demo-service

A tiny, **fully isolated** demo microservice used only for version-control testing.

- No dependencies (Python standard library only).
- Imports no project code; touches nothing else in this repository.
- **Not** part of any Docker build or Cloud Run deployment — the app images only
  copy `apps/*`, so this folder is never packaged or shipped.
- Safe to delete at any time with zero impact on the rest of the project.

## Run
```sh
python3 standalone-demo-service/main.py
# GET http://localhost:8080/health   -> {"status":"ok",...}
# GET http://localhost:8080/echo?msg=hi -> {"echo":"hi"}
```
