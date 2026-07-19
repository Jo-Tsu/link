FROM node:24-bookworm-slim AS build

WORKDIR /app

COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

COPY . .
RUN npm run build

FROM node:24-bookworm-slim AS runtime

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=41737

WORKDIR /app

COPY --chown=node:node --from=build /app/.output ./.output

USER node

EXPOSE 41737

CMD ["node", ".output/server/index.mjs"]
