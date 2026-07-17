# Rental-Day Runbook (M9: Tasks 9.2 + 9.5, one session)

Protocol: `docs/calibration.md`. Hard cap **$40**; expected ~2-3 hours of g5.xlarge
(~$3). Set a phone timer at launch. Everything below is copy-paste in order.

## 0. Before launching (already done / verify)
- [ ] AWS quota "Running On-Demand G and VT instances" >= 4 vCPUs (approved)
- [ ] NGC account + API key (ngc.nvidia.com -> Setup -> Generate API Key)
- [ ] This `session_kit/` folder ready on the Mac

## 1. Launch (AWS console)
EC2 -> Launch instance:
- Name `finops-calibration` | AMI: search "NVIDIA GPU-Optimized AMI" (or "Deep
  Learning Base GPU AMI (Ubuntu)") | Type **g5.xlarge** | Key pair: create/download
  `calibration.pem` | Storage: 100 GB gp3 | Launch.
- Note the public IP. **Start the timer.**

## 2. Connect + upload the kit
```bash
chmod 400 ~/Downloads/calibration.pem
scp -i ~/Downloads/calibration.pem -r session_kit ubuntu@<IP>:/home/ubuntu/kit
ssh -i ~/Downloads/calibration.pem ubuntu@<IP>
nvidia-smi   # sanity: the A10G is there; note driver version in the log
```

## 3. Pull Isaac Sim (on the instance)
```bash
docker login nvcr.io    # user: $oauthtoken   password: <your NGC API key>
docker pull nvcr.io/nvidia/isaac-sim:4.2.0   # check current tag on NGC if this 404s
```
Record the exact tag used.

## 4. Smoke test (10 frames)
```bash
cd /home/ubuntu
sed 's/num_frames=120/num_frames=10/' kit/scripts/r1_ref.py > kit/scripts/smoke.py
date +%s > kit/out/smoke_start.txt
docker run --rm --gpus all -e ACCEPT_EULA=Y -v /home/ubuntu/kit:/kit \
  nvcr.io/nvidia/isaac-sim:4.2.0 ./python.sh /kit/scripts/smoke.py \
  2>&1 | tee kit/out/smoke.log
ls kit/out/smoke* && python3 kit/extract_timings.py kit/out/r1_ref --warmup 2 || true
```
Frames appearing = the adapter's output runs on the real stack. If errors: read the
log; the likely suspects are the container tag or a Replicator API rename - fix in
the script, note the diff for the adapter.

## 5. The run matrix (per docs/calibration.md section 3)
For each of r1_ref, r2_scaling, r3_geom_mods, r4_annot_mods, r5_raster:
```bash
R=r1_ref   # repeat for each
date +%s > kit/out/${R}_start.txt
docker run --rm --gpus all -e ACCEPT_EULA=Y -v /home/ubuntu/kit:/kit \
  nvcr.io/nvidia/isaac-sim:4.2.0 ./python.sh /kit/scripts/${R}.py \
  2>&1 | tee kit/out/${R}.log
python3 kit/extract_timings.py kit/out/${R} --start-epoch kit/out/${R}_start.txt \
  | tee kit/out/${R}_timing.json
```
I1 (ingestion): the three `ingestion_s` values from r1/r2/r3 runs serve as the trials.
Check each timing JSON: `cv_acceptable: true` (else re-run that R with 300 frames per
the protocol).

## 6. The coverage pair (9.5)
```bash
for R in cov_redundant cov_trimmed; do
  docker run --rm --gpus all -e ACCEPT_EULA=Y -v /home/ubuntu/kit:/kit \
    nvcr.io/nvidia/isaac-sim:4.2.0 ./python.sh /kit/scripts/${R}.py \
    2>&1 | tee kit/out/${R}.log
done
```

## 7. Bring everything home, then TERMINATE
```bash
tar czf calibration_session.tgz kit/out kit/scripts kit/plans
exit
scp -i ~/Downloads/calibration.pem ubuntu@<IP>:/home/ubuntu/calibration_session.tgz .
```
AWS console -> EC2 -> Instance state -> **Terminate** (not stop) -> confirm the EBS
volume shows "deleted on termination". Billing console next day: confirm total.

## 8. Salvage rule (protocol section 5)
If anything eats the session: r1_ref + one ingestion number alone are enough to ship
Task 9.3. Everything else improves it.
