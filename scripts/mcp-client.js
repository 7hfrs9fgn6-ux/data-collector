// scripts/mcp-client.js
// 简单的 MCP 客户端，用于调用 cn-funds-mcp 的 get_northbound_capital 工具
// 在 GitHub Actions 中通过 Node.js 运行

const { spawn } = require('child_process');
const fs = require('fs');

// 启动 cn-funds-mcp 服务器进程
const server = spawn('npx', ['-y', 'cn-funds-mcp'], {
  stdio: ['pipe', 'pipe', 'pipe']
});

let initialized = false;
let responseData = '';
let timeoutId = null;

// 发送 JSON-RPC 请求
function sendRequest(method, params = {}, id = 1) {
  const request = {
    jsonrpc: '2.0',
    id: id,
    method: method,
    params: params
  };
  server.stdin.write(JSON.stringify(request) + '\n');
}

// 处理服务器输出
server.stdout.on('data', (data) => {
  const lines = data.toString().split('\n');
  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      const msg = JSON.parse(line);
      // 处理初始化请求（服务器会先发一个 initialize 请求）
      if (msg.method === 'initialize') {
        // 响应初始化
        const initResponse = {
          jsonrpc: '2.0',
          id: msg.id,
          result: {
            protocolVersion: '2024-11-05',
            capabilities: {}
          }
        };
        server.stdin.write(JSON.stringify(initResponse) + '\n');
        initialized = true;
        // 初始化完成后，立即调用工具
        sendRequest('tools/call', {
          name: 'get_northbound_capital',
          arguments: {}
        }, 2);
      } else if (msg.id === 2 && msg.result) {
        // 工具调用结果
        const result = msg.result;
        if (result.content && result.content[0]) {
          const text = result.content[0].text;
          // 尝试解析 JSON
          try {
            const data = JSON.parse(text);
            // 输出标准 JSON
            console.log(JSON.stringify(data, null, 2));
          } catch {
            // 如果不是 JSON，按原样输出
            console.log(text);
          }
        } else {
          console.log(JSON.stringify(result, null, 2));
        }
        // 正常退出
        server.kill();
        clearTimeout(timeoutId);
        process.exit(0);
      } else if (msg.error) {
        console.error('MCP 错误:', JSON.stringify(msg.error, null, 2));
        server.kill();
        clearTimeout(timeoutId);
        process.exit(1);
      }
    } catch (e) {
      // 忽略非 JSON 输出（例如服务器启动日志）
    }
  }
});

server.stderr.on('data', (data) => {
  // 将 stderr 输出到 stderr，但不中断流程
  process.stderr.write(data);
});

server.on('close', (code) => {
  if (code !== 0 && code !== null) {
    console.error(`服务器进程异常退出，退出码: ${code}`);
    process.exit(code);
  }
});

server.on('error', (err) => {
  console.error('启动服务器失败:', err.message);
  process.exit(1);
});

// 启动通信：发送初始化请求（客户端先发）
setTimeout(() => {
  sendRequest('initialize', {
    protocolVersion: '2024-11-05',
    capabilities: {},
    clientInfo: { name: 'github-actions-client', version: '1.0.0' }
  }, 1);
}, 100);

// 超时保护：30 秒后强制退出
timeoutId = setTimeout(() => {
  console.error('⏰ 30秒超时，强制退出');
  server.kill();
  process.exit(1);
}, 30000);
