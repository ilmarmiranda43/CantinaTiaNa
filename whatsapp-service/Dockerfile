FROM node:20-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY index.js auth_postgres.js ./

EXPOSE 3001
CMD ["npm", "start"]

