FROM imlteam/python-service-base:6.2.0-dev

CMD ["python", "./manage.py", "chroma_service", "--name=http_agent", "http_agent", "--gevent", "--console"]