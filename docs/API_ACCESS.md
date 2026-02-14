# API Access

The API documentation is not available on the deployed application for security reasons.

## Viewing the Documentation

To inspect the API definitions, you can use the `openapi.json` file located in the root of this repository.

### Using Swagger Editor

1.  Open [Swagger Editor](https://editor.swagger.io/).
2.  File -> Import File -> Select `openapi.json` from the root of this repository.
3.  You will be able to browse the API documentation interactively.

### Local Development

If you are developing locally, you can use a VS Code extension like "OpenAPI (Swagger) Editor" to preview the `openapi.json` file.
You can also generate a fresh copy of the schema by running:

```bash
make openapi
```

This will update the `openapi.json` file in the root directory.
