## For OSX

```bash
brew install serverless
```

Install plugins:

```bash
sls plugin install --name serverless-python-requirements
sls plugin install --name serverless-wsgi
```


Deploy and view logs:

```bash
sls deploy && sls logs -f app -t
```
