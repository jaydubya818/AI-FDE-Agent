FROM node:24.6.0-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web ./apps/web
ARG NEXT_PUBLIC_AI_FDE_API_URL
ENV NEXT_PUBLIC_AI_FDE_API_URL=$NEXT_PUBLIC_AI_FDE_API_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm --dir apps/web build

FROM node:24.6.0-alpine AS runtime
RUN addgroup --system --gid 10001 ai-fde \
    && adduser --system --uid 10001 --ingroup ai-fde ai-fde
WORKDIR /app/apps/web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=builder --chown=ai-fde:ai-fde /app/apps/web/.next/standalone /app
COPY --from=builder --chown=ai-fde:ai-fde /app/apps/web/.next/static ./.next/static
USER ai-fde
EXPOSE 3000
CMD ["node", "server.js"]
