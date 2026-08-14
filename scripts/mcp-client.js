#!/usr/bin/env node
/**
 * 简单 MCP 客户端 - 调用 cn-funds-mcp 的 get_northbound_capital
 * 在 GitHub Actions 中通过 Node.js 运行
 */

const { spawn } = require('child_process');
const fs = require('fs');

// 启动 cn-funds-mcp 服务器
const server = spawn('npx', ['-y', 'cn-funds-mcp'], {
  stdio: ['pipe', 'pipe', 'pipe']
});

let responseData = '';
let initialized = false;

// 发送 JSON-RPC 请求
function sendRequest(method, params = {}) {
  const request = {
    jsonrpc: '2.0',
    id: 1,
    method: method,
    params: params
  };
  server.stdin.write(JSON.stringify(request) + '\n');
}

// 处理服务器响应
server.stdout.on('data', (data) => {
  const lines = data.toString().split('\n');
  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      const msg = JSON.parse(line);
      if (msg.method === 'initialize') {
        // 响应初始化请求
        const initResponse = {
          jsonrpc: '2.0',
          id: msg.id,
          result: { protocolVersion: '2024-11-05', capabilities: {} }
        };
        server.stdin.write(JSON.stringify(initResponse) + '\n');
        initialized = true;
        // 初始化完成后，调用 get_northbound_capital
        setTimeout(() => sendRequest('tools/call', {
          name: 'get_northbound_capital',
          arguments: {}
        }), 100);
      } else if (msg.result) {
        // 工具调用结果
        const result = msg.result;
        if (result.content && result.content[0]) {
          const text = result.content[0].text;
          try {
            const data = JSON.parse(text);
            console.log(JSON.stringify(data, null, 2));
          } catch {
            console.log(text);
          }
        } else {
          console.log(JSON.stringify(result, null, 2));
        }
        server.kill();
      } else if (msg.error) {
        console.error('MCP 错误:', JSON.stringify(msg.error, null, 2));
        server.kill();
        process.exit(1);
      }
    } catch (e) {
      // 忽略非 JSON 输出
    }
  }
});

server.stderr.on('data', (data) => {
  console.error('stderr:', data.toString());
});

server.on('close', (code) => {
  if (code !== 0 && code !== null) {
    console.error(`服务器退出码: ${code}`);
    process.exit(code);
  }
});

// 超时保护
setTimeout(() => {
  console.error('超时，强制退出');
  server.kill();
  process.exit(1);
}, 30000);

// 启动初始化请求
sendRequest('initialize', {
  protocolVersion: '2024-11-05',
  capabilities: {},
  clientInfo: { name: 'github-actions-client', version: '1.0.0' }
});
