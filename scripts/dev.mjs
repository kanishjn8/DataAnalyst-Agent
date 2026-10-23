import { spawn } from 'node:child_process';
const processes = [
  spawn('uv', ['run', '--directory', 'backend', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '4000'], { stdio: 'inherit' }),
  spawn(process.execPath, ['node_modules/next/dist/bin/next', 'dev'], { stdio: 'inherit' }),
];
let stopping = false;
function stop(code = 0) { if (stopping) return; stopping = true; processes.forEach(child => child.kill('SIGTERM')); process.exitCode = code; }
processes.forEach(child => { child.on('error', () => stop(1)); child.on('exit', code => { if (!stopping) stop(code ?? 1); }); });
process.on('SIGINT', () => stop()); process.on('SIGTERM', () => stop());
