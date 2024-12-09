FROM nginx
COPY server_files/certs /etc/nginx/certs
ARG config_file
COPY ${config_file} /etc/nginx/conf.d/default.conf
EXPOSE 443
