import { NextRequest, NextResponse } from 'next/server';
import { spawn } from 'node:child_process';
import { join } from 'node:path';

export const runtime = 'nodejs';

function runDocumentManager(payload: object): Promise<any> {
  return new Promise((resolve, reject) => {
    const projectRoot = join(process.cwd(), '..');

    const pythonPath = join(
      projectRoot,
      'venv',
      'Scripts',
      'python.exe'
    );

    const scriptPath = join(
      projectRoot,
      'rag',
      'document_manager.py'
    );

    const python = spawn(
      pythonPath,
      [scriptPath],
      {
        cwd: projectRoot,
        stdio: ['pipe', 'pipe', 'pipe'],
      }
    );

    let stdout = '';
    let stderr = '';

    python.stdout.on('data', (data) => {
      stdout += data.toString();
    });

    python.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    python.on('error', (error) => {
      reject(error);
    });

    python.on('close', (code) => {
      if (code !== 0) {
        reject(
          new Error(
            stderr || `Python exited with code ${code}`
          )
        );
        return;
      }

      try {
        const result = JSON.parse(stdout);

        if (!result.success) {
          reject(
            new Error(result.error || 'Upload failed')
          );
          return;
        }

        resolve(result.data);
      } catch {
        reject(
          new Error(
            `Invalid response from document manager: ${stdout}`
          )
        );
      }
    });

    python.stdin.write(
      JSON.stringify(payload)
    );

    python.stdin.end();
  });
}

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();

    const file = formData.get('file');

    if (!(file instanceof File)) {
      return NextResponse.json(
        {
          detail: 'No file was uploaded.',
        },
        { status: 400 }
      );
    }

    if (!file.name.toLowerCase().endsWith('.md')) {
      return NextResponse.json(
        {
          detail: 'Only Markdown (.md) files are supported.',
        },
        { status: 400 }
      );
    }

    const content = await file.text();

    const result = await runDocumentManager({
      action: 'upload',
      name: file.name,
      content,
    });

    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      {
        detail: `Failed to upload document: ${
          (err as Error).message
        }`,
      },
      { status: 500 }
    );
  }
}