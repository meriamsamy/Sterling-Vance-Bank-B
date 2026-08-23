import { NextResponse } from 'next/server';
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
            new Error(result.error || 'Delete failed')
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

export async function DELETE(
  _req: Request,
  {
    params,
  }: {
    params: { documentId: string };
  }
) {
  try {
    const documentId = decodeURIComponent(
      params.documentId
    );

    if (!documentId.toLowerCase().endsWith('.md')) {
      return NextResponse.json(
        {
          detail: 'Only Markdown documents can be deleted.',
        },
        { status: 400 }
      );
    }

    await runDocumentManager({
      action: 'delete',
      name: documentId,
    });

    return NextResponse.json({
      success: true,
    });
  } catch (err) {
    return NextResponse.json(
      {
        detail: `Failed to delete document: ${
          (err as Error).message
        }`,
      },
      { status: 500 }
    );
  }
}