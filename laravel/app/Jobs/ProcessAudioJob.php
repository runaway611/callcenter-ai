<?php

namespace App\Jobs;

use App\Models\Call;
use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Bus\Dispatchable;
use Illuminate\Queue\InteractsWithQueue;
use Illuminate\Queue\SerializesModels;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class ProcessAudioJob implements ShouldQueue
{
    use Dispatchable, InteractsWithQueue, Queueable, SerializesModels;

    public int $timeout = 300;
    public int $tries   = 3;

    public function __construct(public Call $call) {}

    public function handle(): void
    {
        $this->call->update(['status' => 'processing']);

        try {
            $response = Http::timeout(280)
                ->attach('audio', file_get_contents(storage_path('app/audios/' . $this->call->filename)), $this->call->filename)
                ->post(config('services.fastapi.url') . '/process-audio', [
                    'call_id'   => $this->call->uuid,
                    'tenant_id' => $this->call->tenant_id,
                ]);

            if ($response->successful()) {
                $data = $response->json();

                $this->call->update([
                    'status'        => 'completed',
                    'transcription' => $data['transcription'] ?? null,
                    'analysis'      => $data['analysis'] ?? null,
                    'score'         => $data['analysis']['score_asesor'] ?? null,
                ]);
            } else {
                $this->call->update(['status' => 'error']);
                Log::error('FastAPI error', ['response' => $response->body()]);
            }
        } catch (\Exception $e) {
            $this->call->update(['status' => 'error']);
            Log::error('ProcessAudioJob failed', ['error' => $e->getMessage()]);
        }
    }
}
