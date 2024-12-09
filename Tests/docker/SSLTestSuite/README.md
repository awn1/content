# SSL Test Suite

This test creates a server using custom nginx configurations inside docker, and then runs clients code that uses BaseClient inside tested docker image.

### Certificate creation

For this test suite we used self-signed certificate, that was generated using the following commands.
First create a file named **openssl-san.cnf**, with the following content:

```
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
C = IL
ST = IL
L = TLV
CN = nginx-container

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = nginx-container
```

Then run the following command.

```openssl req -x509 -newkey rsa:4096 -keyout server.key -out server.crt -days 365 -nodes -config openssl-san.cnf ```

The generated files content saved in GitLab CI/CD variables: SSL_TEST_PRIVATE_KEY, SSL_TEST_CERT_FILE.

In order to update the client to use the self-signed certificate use the command:
```export REQUESTS_CA_BUNDLE=/client/certificate.pem```

