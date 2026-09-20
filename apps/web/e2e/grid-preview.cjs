const next = require('next');
const http = require('http');
// Separate compilation output; no backend needed because the test mocks APIs.
const app = next({dev:true, dir:process.cwd(), conf:{distDir:'.next-grid-uat',transpilePackages:['@career-os/core','@career-os/ui']}});
app.prepare().then(() => http.createServer(app.getRequestHandler()).listen(5057,'127.0.0.1'));
