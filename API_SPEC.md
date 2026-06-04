# API Spec

## `POST /translate`

Request:

```json
{
  "text": "Hello",
  "source_language": "auto",
  "target_language": "vi",
  "provider": "google"
}
```

Response:

```json
{
  "translated_text": "Xin chao",
  "source_language": "en",
  "target_language": "vi",
  "provider": "google",
  "cached": false
}
```

Errors:

- `400`: unknown translation provider.
- `422`: invalid request payload.
- `502`: configured provider failed.
