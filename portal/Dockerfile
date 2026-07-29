# syntax=docker/dockerfile:1.7
FROM node:22.23.1-alpine3.24 AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:22.23.1-alpine3.24 AS runtime

ENV NODE_ENV=production \
    WRANGLER_WRITE_LOGS=false \
    WRANGLER_LOG_PATH=/tmp/wrangler.log \
    MINIFLARE_REGISTRY_PATH=/tmp/miniflare-registry

WORKDIR /app
RUN rm -rf /usr/local/lib/node_modules/npm \
    /usr/local/bin/npm \
    /usr/local/bin/npx
COPY --from=build --chown=node:node /app/dist/standalone ./

USER node
EXPOSE 3000

HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=5 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

CMD ["node", "server.js"]
