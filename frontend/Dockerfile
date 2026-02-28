FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/nginx.conf
COPY frontend/index.html /usr/share/nginx/html/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
