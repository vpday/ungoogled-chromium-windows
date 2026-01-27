const core = require('@actions/core');
const io = require('@actions/io');
const exec = require('@actions/exec');
const {DefaultArtifactClient} = require('@actions/artifact');
const glob = require('@actions/glob');
const path = require('path');

async function run() {
    process.on('SIGINT', function() {
    })
    const finished = core.getBooleanInput('finished', {required: true});
    const from_artifact = core.getBooleanInput('from_artifact', {required: true});
    const x86 = core.getBooleanInput('x86', {required: false})
    const arm = core.getBooleanInput('arm', {required: false})
    console.log(`finished: ${finished}, artifact: ${from_artifact}`);
    if (finished) {
        core.setOutput('finished', true);
        return;
    }

    const WORK_DIR = process.env.GITHUB_WORKSPACE || process.cwd();
    const BUILD_DIR = path.join(WORK_DIR, 'build');
    console.log(`Working Directory: ${WORK_DIR}`);

    const artifact = new DefaultArtifactClient();
    const artifactName = x86 ? 'build-artifact-x86' : (arm ? 'build-artifact-arm' : 'build-artifact');

    if (from_artifact) {
        const artifactInfo = await artifact.getArtifact(artifactName);
        await artifact.downloadArtifact(artifactInfo.artifact.id, {path: BUILD_DIR});
        const zipPath = path.join(BUILD_DIR, 'artifacts.zip');
        await exec.exec('7z', ['x', zipPath, `-o${BUILD_DIR}`, '-y']);
        await io.rmRF(zipPath);
    }

    const args = ['build.py', '--ci', '-j', '2']
    if (x86)
        args.push('--x86')
    if (arm)
        args.push('--arm')
    await exec.exec('python3', ['-m', 'pip', 'install', 'httplib2==0.22.0'], {
        cwd: WORK_DIR,
        ignoreReturnCode: true
    });
    const retCode = await exec.exec('python3', args, {
        cwd: WORK_DIR,
        ignoreReturnCode: true
    });
    if (retCode === 0) {
        core.setOutput('finished', true);
        const globPattern = path.join(BUILD_DIR, 'ungoogled-chromium*');
        const globber = await glob.create(globPattern, {matchDirectories: false});
        let packageList = await globber.glob();
        const finalArtifactName = x86 ? 'chromium-x86' : (arm ? 'chromium-arm' : 'chromium');
        for (let i = 0; i < 5; ++i) {
            try {
                await artifact.deleteArtifact(finalArtifactName);
            } catch (e) {
                // ignored
            }
            try {
                await artifact.uploadArtifact(finalArtifactName, packageList,
                    BUILD_DIR, {retentionDays: 4, compressionLevel: 0});
                break;
            } catch (e) {
                console.error(`Upload artifact failed: ${e}`);
                // Wait 10 seconds between the attempts
                await new Promise(r => setTimeout(r, 10000));
            }
        }
    } else {
        await new Promise(r => setTimeout(r, 5000));
        const zipTarget = path.join(WORK_DIR, 'artifacts.zip');
        const srcDir = path.join(BUILD_DIR, 'src');
        await exec.exec('7z', ['a', '-tzip', zipTarget, srcDir, '-mx=3', '-mtc=on'], {ignoreReturnCode: true});
        for (let i = 0; i < 5; ++i) {
            try {
                await artifact.deleteArtifact(artifactName);
            } catch (e) {
                // ignored
            }
            try {
                await artifact.uploadArtifact(artifactName, [zipTarget],
                    WORK_DIR, {retentionDays: 4, compressionLevel: 0});
                break;
            } catch (e) {
                console.error(`Upload artifact failed: ${e}`);
                // Wait 10 seconds between the attempts
                await new Promise(r => setTimeout(r, 10000));
            }
        }
        core.setOutput('finished', false);
    }
}

run().catch(err => core.setFailed(err.message));
