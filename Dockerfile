FROM amazon/aws-lambda-python:3.10.2024.09.06.09

COPY . ${LAMBDA_TASK_ROOT}

RUN pip install -r requirements.txt
# # Copy function code
# COPY app.py ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler (could also be done as a parameter override outside of the Dockerfile)
CMD [ "wsgi_handler.handler" ]