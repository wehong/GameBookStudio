// 웹 플레이어(내보낸 HTML 안에서 도는 게임) 빌드:  npm install && node build.js
// 결과물은 ../gbengine/web/player.js, player.css 로 복사됩니다.
const esbuild = require('esbuild');
const fs = require('fs');
const path = require('path');
const out = path.join(__dirname, '..', 'gbengine', 'web');
esbuild.buildSync({
  entryPoints: [path.join(__dirname, 'src', 'standalone.js')],
  bundle: true, format: 'iife', target: ['es2020'], charset: 'utf8', minify: true,
  outfile: path.join(out, 'player.js'),
});
fs.copyFileSync(path.join(__dirname, 'src', 'player.css'), path.join(out, 'player.css'));
console.log('built', out);
