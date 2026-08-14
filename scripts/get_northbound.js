// scripts/get_northbound.js
const { spawn } = require('child_process');
const fs = require('fs');

async function getNorthboundCapital() {
  return new Promise((resolve, reject) => {
    const proc = spawn('npx', ['-y', 'cn-funds-mcp', 'get_northbound_capital'], {
      stdio: ['pipe', 'pipe', 'pipe']
    });

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (data) => { stdout += data.toString(); });
    proc.stderr.on('data', (data) => { stderr += data.toString(); });

    proc.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`进程退出码 ${code}: ${stderr}`));
        return;
      }
      try {
        const result = JSON.parse(stdout);
        resolve(result);
      } catch (e) {
        // 如果输出不是JSON，尝试解析为文本
        resolve({ data: stdout.trim() });
      }
    });

    proc.on('error', reject);
  });
}

getNorthboundCapital()
  .then(data => {
    fs.writeFileSync('staging/north_flow_raw.json', JSON.stringify(data, null, 2));
    console.log('北向资金数据已保存');
  })
  .catch(err => {
    console.error('获取失败:', err.message);
    process.exit(1);
  });
