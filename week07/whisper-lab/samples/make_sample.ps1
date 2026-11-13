# Generate a speech sample with the Windows built-in voice, so Whisper Lab has
# something to transcribe without downloading audio or hunting for a copyright
# clean recording.
#
#   powershell -ExecutionPolicy Bypass -File samples/make_sample.ps1
#
# Writes demo.wav and demo.reference.txt next to this script. On macOS or
# Linux, record any short clip instead (or use the `say` command with `-o`).

param(
    [string]$Output = (Join-Path $PSScriptRoot "demo.wav")
)

$script = @'
Prague has grown from a settlement stretching from Prague Castle in the north to the fort of Vyšehrad in the south, to become the capital of a modern European country. With archaeological deposits over 10m deep, the city serves as a model for the implementation of comprehensive regulations for the protection of archaeological heritage throughout the Czech Republic.
The mythological princess Libuše prophesies the glory of Prague.
The region was settled as early as the Paleolithic age. Jewish chronicler David Solomon Ganz, citing Cyriacus Spangenberg, claimed that the city was founded as Boihaem in c. 1306 BC by an ancient king, Boyya.[20]
Around the fifth and fourth century BC, a Celtic tribe appeared in the area, later establishing settlements, including the largest Celtic oppidum in Bohemia, Závist, in a present-day Dolní Břežany south of Prague, and naming the region of Bohemia, which means "home of the Boii people".[19][21] In the last century BC, the Celts were slowly driven away by Germanic tribes (Marcomanni, Quadi, Lombards and possibly the Suebi), leading some to place the seat of the Marcomanni king, Maroboduus, in Závist.[22][20] Around the area where present-day Prague stands, the 2nd century map drawn by Roman geographer Ptolemaios mentioned a Germanic city called Casurgis.
'@

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0
$synth.Volume = 100
$synth.SetOutputToWaveFile($Output)
$synth.Speak($script)
$synth.Dispose()

$reference = [System.IO.Path]::ChangeExtension($Output, ".reference.txt")
$script.Trim() -replace "\s+", " " | Set-Content -Path $reference -Encoding utf8

Write-Host "Wrote $Output"
Write-Host "Wrote $reference"
