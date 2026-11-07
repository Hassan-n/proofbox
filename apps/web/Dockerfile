FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY 40-configure-api-url.sh /docker-entrypoint.d/40-configure-api-url.sh
RUN chmod +x /docker-entrypoint.d/40-configure-api-url.sh
COPY index.html /usr/share/nginx/html/index.html
COPY bill /usr/share/nginx/html/bill
COPY case /usr/share/nginx/html/case
COPY letter /usr/share/nginx/html/letter
COPY css /usr/share/nginx/html/css
COPY js /usr/share/nginx/html/js
COPY styleguide.html /usr/share/nginx/html/styleguide.html
COPY vultr.html /usr/share/nginx/html/vultr.html
EXPOSE 80
