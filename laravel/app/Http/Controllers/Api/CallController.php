<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Jobs\ProcessAudioJob;
use App\Models\Call;
use Illuminate\Http\Request;
use Illuminate\Support\Str;
use Illuminate\Support\Facades\Storage;
class CallController extends Controller
{
    public function index(Request $request)
    {
        $calls = Call::where('tenant_id', $request->user()->tenant_id)
            ->orderByDesc('created_at')
            ->paginate(20);

        return response()->json($calls);
    }

    public function store(Request $request)
    {
        $request->validate([
            'audio' => 'required|file|mimes:mp3,wav,m4a,ogg,webm|max:102400',
        ]);

        $file     = $request->file('audio');
        $filename = Str::uuid() . '.' . $file->getClientOriginalExtension();

        // Guardar en storage/app/audios
        $file->move(storage_path('app/audios'), $filename);

        $call = Call::create([
            'tenant_id'     => $request->user()->tenant_id,
            'user_id'       => $request->user()->id,
            'filename'      => $filename,
            'original_name' => $file->getClientOriginalName(),
            'status'        => 'pending',
        ]);

        ProcessAudioJob::dispatch($call);

        return response()->json([
            'message' => 'Audio recibido, procesando.',
            'call_id' => $call->uuid,
            'status'  => $call->status,
        ], 202);
    }

    public function show(Request $request, string $uuid)
    {
        $call = Call::where('uuid', $uuid)
            ->where('tenant_id', $request->user()->tenant_id)
            ->firstOrFail();

        return response()->json($call);
    }
}
