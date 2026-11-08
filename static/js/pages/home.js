/**
 * Home & Dashboard - Navigation Tabs & League Filter Selectors
 */
document.addEventListener('DOMContentLoaded', () => {
function submitHomeRsvp(gameId, responseVal) {
    fetch("/leagues/games/" + gameId + "/rsvp/", {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': '{{ csrf_token }}'
        },
        body: JSON.stringify({ response: responseVal })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            const grp = document.getElementById('homeRsvpGroup');
            if (grp) {
                const btns = grp.querySelectorAll('button');
                btns.forEach(b => {
                    b.classList.remove('btn-accent');
                    b.classList.add('btn-secondary');
                });
                if (responseVal === 'yes') btns[0].classList.add('btn-accent');
                if (responseVal === 'no') btns[1].classList.add('btn-accent');
                if (responseVal === 'maybe') btns[2].classList.add('btn-accent');
            }
        }
    });
}


function switchGameCenterTab(tab) {
    const upcomingDiv = document.getElementById('tabViewUpcoming');
    const resultsDiv = document.getElementById('tabViewResults');
    const btnUpcoming = document.getElementById('btnTabUpcoming');
    const btnResults = document.getElementById('btnTabResults');
    if (tab === 'upcoming') {
        if (upcomingDiv) upcomingDiv.style.display = 'block';
        if (resultsDiv) resultsDiv.style.display = 'none';
        if (btnUpcoming) { btnUpcoming.classList.add('btn-accent'); btnUpcoming.classList.remove('btn-secondary'); }
        if (btnResults) { btnResults.classList.remove('btn-accent'); btnResults.classList.add('btn-secondary'); }
    } else {
        if (upcomingDiv) upcomingDiv.style.display = 'none';
        if (resultsDiv) resultsDiv.style.display = 'block';
        if (btnUpcoming) { btnUpcoming.classList.remove('btn-accent'); btnUpcoming.classList.add('btn-secondary'); }
        if (btnResults) { btnResults.classList.add('btn-accent'); btnResults.classList.remove('btn-secondary'); }
    }
}

});
