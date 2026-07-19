FROM node:22-bookworm-slim

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

EXPOSE 41737

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "41737"]
