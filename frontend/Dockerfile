FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . /app

EXPOSE 80

# 使用 nginx 托管构建产物
RUN apk add --no-cache nginx && \
    npm run build && \
    rm -f /etc/nginx/http.d/default.conf

COPY nginx.conf /etc/nginx/http.d/app.conf

CMD ["nginx", "-g", "daemon off;"]
