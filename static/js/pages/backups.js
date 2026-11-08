/**
 * System Administration - Backup & Cloud Storage Management Scripts
 */
document.addEventListener('DOMContentLoaded', () => {
function toggleStorageFields() {
    const st = document.getElementById('storage_type').value;
    document.getElementById('local_config_block').style.display = st === 'LOCAL' ? 'block' : 'none';
    document.getElementById('s3_config_block').style.display = st === 'S3' ? 'block' : 'none';
    document.getElementById('cifs_config_block').style.display = st === 'CIFS' ? 'block' : 'none';
    document.getElementById('nfs_config_block').style.display = st === 'NFS' ? 'block' : 'none';
}

function testTargetConnection() {
    const resElem = document.getElementById('test_conn_result');
    resElem.innerHTML = '<span style="color:var(--text-muted);">Testing connection...</span>';
    
    const formData = new FormData();
    formData.append('csrfmiddlewaretoken', '{{ csrf_token }}');
    formData.append('storage_type', document.getElementById('storage_type').value);
    formData.append('local_path', document.getElementById('local_path').value);
    formData.append('s3_bucket', document.getElementById('s3_bucket').value);
    formData.append('s3_region', document.getElementById('s3_region').value);
    formData.append('s3_access_key', document.getElementById('s3_access_key').value);
    formData.append('s3_secret_key', document.getElementById('s3_secret_key').value);
    formData.append('s3_endpoint_url', document.getElementById('s3_endpoint_url').value);
    formData.append('s3_prefix', document.getElementById('s3_prefix').value);
    formData.append('cifs_server', document.getElementById('cifs_server').value);
    formData.append('cifs_share', document.getElementById('cifs_share').value);
    formData.append('cifs_subpath', document.getElementById('cifs_subpath').value);
    formData.append('cifs_username', document.getElementById('cifs_username').value);
    formData.append('cifs_password', document.getElementById('cifs_password').value);
    formData.append('cifs_domain', document.getElementById('cifs_domain').value);
    formData.append('nfs_server', document.getElementById('nfs_server').value);
    formData.append('nfs_export', document.getElementById('nfs_export').value);
    formData.append('nfs_subpath', document.getElementById('nfs_subpath').value);

    fetch('{% url "backup_test_connection_api" %}', {
        method: 'POST',
        body: formData
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            resElem.innerHTML = '<span style="color:#16a34a;">&#10003; ' + data.message + '</span>';
        } else {
            resElem.innerHTML = '<span style="color:#dc2626;">&#10007; ' + data.message + '</span>';
        }
    })
    .catch(err => {
        resElem.innerHTML = '<span style="color:#dc2626;">&#10007; Connection failed: ' + err + '</span>';
    });
}

function confirmRestore(form, filename, isEncrypted) {
    if (!confirm('CAUTION: Restoring from snapshot \"' + filename + '\" will overwrite all database tables with this snapshot. Continue?')) {
        return false;
    }
    if (isEncrypted) {
        const pass = prompt('This backup snapshot is encrypted. Enter AES-256-GCM decryption passphrase:');
        if (pass === null) return false;
        form.querySelector('.restore-passphrase-field').value = pass;
    }
    return true;
}

// Initial display on load
toggleStorageFields();

});
